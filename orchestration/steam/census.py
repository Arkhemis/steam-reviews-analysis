import itertools
import time
from datetime import UTC, datetime

from dagster import (
    AssetExecutionContext,
    MaterializeResult,
    MetadataValue,
    asset,
)

from orchestration.clickhouse import ClickHouseResource
from orchestration.steam.resources import SteamResource

# GetItems plafonne à ~250 ids par requête (URL trop longue au-delà).
CENSUS_BATCH_SIZE = 200


STEAM_APP_IDS_SQL = """
SELECT DISTINCT steam_app_id AS app_id
FROM igdb_games
WHERE steam_app_id IS NOT NULL
ORDER BY steam_app_id
"""

KNOWN_APP_IDS_SQL = "SELECT DISTINCT app_id FROM steam_review_counts"

# Les totaux (dont les clés activées ailleurs) restent écrits par le backfill et
# l'incrémental depuis la page 1 de /appreviews. Un jeu backfillé avant ce
# recensement prend le compteur du jour comme point de départ, faute de mieux :
# ses reviews ne sont pas perdues, le checkpoint les rattrapera à son prochain mouvement.
# Les SET lisent les valeurs d'avant l'UPDATE, comme l'ancien ON CONFLICT.
UPDATE_STEAM_COUNT_SQL = """
UPDATE steam_review_counts
SET steam_count            = transform(app_id, {ids:Array(UInt32)}, {counts:Array(Int64)}, toInt64(0)),
    steam_count_checked_at = now64(6),
    synced_steam_count     = coalesce(
        synced_steam_count,
        if(
            last_backfill_at IS NOT NULL,
            transform(app_id, {ids:Array(UInt32)}, {counts:Array(Int64)}, toInt64(0)),
            NULL
        )
    )
WHERE app_id IN {ids:Array(UInt32)}
"""


def write_steam_counts(
    clickhouse: ClickHouseResource, counts: list[tuple[int, int]], known: set[int]
) -> None:
    """Insère les jeux absents de la table, met à jour les autres ; complète `known`."""
    new = [(app_id, count) for app_id, count in counts if app_id not in known]
    existing = [(app_id, count) for app_id, count in counts if app_id in known]
    clickhouse.insert(
        "steam_review_counts",
        [(app_id, count, datetime.now(UTC)) for app_id, count in new],
        ["app_id", "steam_count", "steam_count_checked_at"],
    )
    known.update(app_id for app_id, _ in new)
    if existing:
        ids, values = zip(*existing)
        clickhouse.command(
            UPDATE_STEAM_COUNT_SQL, {"ids": list(ids), "counts": list(values)}
        )


def steam_review_count(item: dict) -> int | None:
    """Compteur de reviews d'une fiche GetItems, None si Steam n'en donne pas."""
    if item.get("success") != 1:
        return None
    return ((item.get("reviews") or {}).get("summary_filtered") or {}).get(
        "review_count"
    )


@asset(
    group_name="ingest",
    deps=["igdb_games"],
    description=(
        "Compteur de reviews Steam de chaque jeu via GetItems (lots de 200) -> "
        "raw.steam_review_counts.steam_count : le signal « a bougé » de "
        "l'incrémental. Les totaux viennent de la page 1 de /appreviews."
    ),
)
def steam_review_counts(
    context: AssetExecutionContext,
    steam: SteamResource,
    clickhouse: ClickHouseResource,
) -> MaterializeResult:
    app_ids = [row["app_id"] for row in clickhouse.query(STEAM_APP_IDS_SQL)]
    known = {row["app_id"] for row in clickhouse.query(KNOWN_APP_IDS_SQL)}
    total = len(app_ids)
    context.log.info(
        f"Recensement GetItems de {total} jeux Steam (lots de {CENSUS_BATCH_SIZE})"
    )

    scanned = 0
    counted = 0
    batches_failed = 0
    start = time.monotonic()
    for batch in itertools.batched(app_ids, CENSUS_BATCH_SIZE):
        scanned += len(batch)
        try:
            items = steam.get_store_items(
                list(batch), include_release=False, include_reviews=True
            )
        except Exception:
            context.log.exception(f"Lot à partir de app_id={batch[0]} en échec")
            batches_failed += 1
            continue

        # Un id en double dans la réponse créerait deux lignes pour le même jeu.
        counts = {
            item["id"]: count
            for item in items
            if (count := steam_review_count(item)) is not None
        }
        write_steam_counts(clickhouse, list(counts.items()), known)
        counted += len(counts)

        elapsed = time.monotonic() - start
        context.log.info(
            f"Recensé {scanned}/{total} ({scanned / total:.0%}) "
            f"— {scanned / elapsed:.0f} jeux/s — {counted} compteurs"
        )

    if batches_failed:
        context.log.warning(f"{batches_failed} lots en échec, repris au prochain run")
    return MaterializeResult(
        metadata={
            "apps_scanned": MetadataValue.int(scanned),
            "apps_counted": MetadataValue.int(counted),
            "batches_failed": MetadataValue.int(batches_failed),
        }
    )
