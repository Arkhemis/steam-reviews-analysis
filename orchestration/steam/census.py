import itertools
import time

from dagster import (
    AssetExecutionContext,
    MaterializeResult,
    MetadataValue,
    asset,
)

from orchestration.postgres import PostgresResource
from orchestration.steam.resources import SteamResource

# GetItems plafonne à ~250 ids par requête (URL trop longue au-delà).
CENSUS_BATCH_SIZE = 200


STEAM_APP_IDS_SQL = """
SELECT DISTINCT steam_app_id AS app_id
FROM raw.igdb_games
WHERE steam_app_id IS NOT NULL
ORDER BY steam_app_id;
"""

# Les totaux (dont les clés activées ailleurs) restent écrits par le backfill et
# l'incrémental depuis la page 1 de /appreviews. Un jeu backfillé avant ce
# recensement prend le compteur du jour comme point de départ, faute de mieux :
# ses reviews ne sont pas perdues, le checkpoint les rattrapera à son prochain mouvement.
UPSERT_STEAM_COUNT_SQL = """
INSERT INTO raw.steam_review_counts (app_id, steam_count, steam_count_checked_at)
VALUES (%s, %s, now())
ON CONFLICT (app_id) DO UPDATE
SET steam_count            = EXCLUDED.steam_count,
    steam_count_checked_at = now(),
    synced_steam_count     = COALESCE(
        raw.steam_review_counts.synced_steam_count,
        CASE
            WHEN raw.steam_review_counts.last_backfill_at IS NOT NULL
                THEN EXCLUDED.steam_count
        END
    );
"""


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
    postgres: PostgresResource,
) -> MaterializeResult:
    app_ids = [row["app_id"] for row in postgres.fetch_all(STEAM_APP_IDS_SQL)]
    total = len(app_ids)
    context.log.info(
        f"Recensement GetItems de {total} jeux Steam (lots de {CENSUS_BATCH_SIZE})"
    )

    scanned = 0
    counted = 0
    batches_failed = 0
    start = time.monotonic()
    with postgres.connect() as conn:
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

            rows = [
                (item["id"], count)
                for item in items
                if (count := steam_review_count(item)) is not None
            ]
            with conn.cursor() as cur:
                cur.executemany(UPSERT_STEAM_COUNT_SQL, rows)
            conn.commit()
            counted += len(rows)

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
