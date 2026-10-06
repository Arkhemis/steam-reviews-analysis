import itertools
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from dagster import (
    AssetExecutionContext,
    MaterializeResult,
    MetadataValue,
    asset,
)

from orchestration.clickhouse import ClickHouseResource
from orchestration.steam.resources import SteamApiError, SteamResource

CENSUS_WORKERS = 8
CENSUS_BATCH_SIZE = 200

# Au-dessus, sondé chaque nuit : un solde ou un review bombing ne doit pas attendre le jour du jeu.
CENSUS_HOT_TOTAL_REVIEWS = 1000

# Jour fixe par jeu (app_id % 7) pour étaler la longue traîne sur la semaine.
# Un jeu délisté n'est plus sondé qu'à son jour, pour repérer une remise en vente.
DUE_APP_IDS_SQL = """
SELECT app_id
FROM (
    SELECT steam_app_id AS app_id, min(first_release_date) AS first_release_date
    FROM igdb_games
    WHERE steam_app_id IS NOT NULL
    GROUP BY steam_app_id
) AS igdb
LEFT JOIN (
    SELECT app_id, 1 AS known, last_backfill_at, total_reviews,
           prev_total_reviews, checked_at, is_delisted
    FROM steam_review_counts
) AS counts USING (app_id)
WHERE counts.known IS NULL
   OR app_id % 7 = toDayOfWeek(now()) % 7
   -- Filet si une nuit a sauté.
   OR checked_at < now() - INTERVAL 8 DAY
   OR (NOT is_delisted AND (
       -- Le backfill lit total_reviews pour sa tolérance d'arrêt.
       last_backfill_at IS NULL
       OR total_reviews >= {hot_total_reviews:Int64}
       OR total_reviews IS DISTINCT FROM prev_total_reviews
       OR first_release_date BETWEEN today() - 7 AND today()
   ))
ORDER BY app_id
SETTINGS join_use_nulls = 1
"""

KNOWN_APP_IDS_SQL = "SELECT app_id FROM steam_review_counts"
DELISTED_APP_IDS_SQL = "SELECT app_id FROM steam_review_counts WHERE is_delisted"

# prev_total_reviews garde le total de la sonde précédente : le signal « a bougé » de la suivante.
UPDATE_CENSUS_SQL = """
UPDATE steam_review_counts
SET prev_total_reviews       = total_reviews,
    total_reviews            = transform(app_id, {ids:Array(UInt32)}, {total_reviews:Array(Nullable(Int64))}, total_reviews),
    total_positive           = transform(app_id, {ids:Array(UInt32)}, {total_positive:Array(Nullable(Int64))}, total_positive),
    total_negative           = transform(app_id, {ids:Array(UInt32)}, {total_negative:Array(Nullable(Int64))}, total_negative),
    review_score             = transform(app_id, {ids:Array(UInt32)}, {review_score:Array(Nullable(Int32))}, review_score),
    review_score_desc        = transform(app_id, {ids:Array(UInt32)}, {review_score_desc:Array(Nullable(String))}, review_score_desc),
    -- Une sonde sans review ne doit pas effacer le signal de l'incrémental.
    latest_timestamp_updated = ifNull(transform(app_id, {ids:Array(UInt32)}, {latest_timestamp_updated:Array(Nullable(Int64))}, latest_timestamp_updated), latest_timestamp_updated),
    checked_at               = now64(6),
    is_delisted              = false
WHERE app_id IN {ids:Array(UInt32)}
"""

MARK_DELISTED_SQL = """
UPDATE steam_review_counts
SET is_delisted = true,
    checked_at  = now64(6)
WHERE app_id IN {ids:Array(UInt32)}
"""


def probe(steam: SteamResource, app_id: int) -> dict[str, Any] | None:
    """Totaux du jeu et timestamp_updated de sa review la plus récemment modifiée."""
    page = steam.get_all_reviews(app_id, num_per_page=1)
    summary = page.get("query_summary") or {}
    if summary.get("total_reviews") is None:
        return None
    reviews = page.get("reviews") or []
    return {
        **summary,
        "latest_timestamp_updated": reviews[0]["timestamp_updated"]
        if reviews
        else None,
    }


def probe_or_delisted(
    steam: SteamResource, app_id: int, delisted: set[int]
) -> dict[str, Any] | None | Literal["delisted"]:
    """Une sonde vide ne vaut délistage que si la fiche store a disparu."""
    result = probe(steam, app_id)
    if result is None and (app_id in delisted or steam.is_removed_from_store(app_id)):
        return "delisted"
    return result


def write_census(
    clickhouse: ClickHouseResource,
    probes: dict[int, dict[str, Any]],
    known: set[int],
    delisted: list[int] | None = None,
) -> None:
    delisted = delisted or []
    new = [app_id for app_id in [*probes, *delisted] if app_id not in known]
    if new:
        clickhouse.insert(
            "steam_review_counts",
            [(app_id, datetime.now(UTC)) for app_id in new],
            ["app_id", "checked_at"],
        )
        known.update(new)
    if delisted:
        clickhouse.command(MARK_DELISTED_SQL, {"ids": delisted})
    if not probes:
        return
    parameters: dict[str, list] = {"ids": list(probes)}
    for field in (
        "total_reviews",
        "total_positive",
        "total_negative",
        "review_score",
        "review_score_desc",
        "latest_timestamp_updated",
    ):
        parameters[field] = [values.get(field) for values in probes.values()]
    clickhouse.command(UPDATE_CENSUS_SQL, parameters)


@asset(
    group_name="ingest",
    deps=["igdb_games"],
    description=(
        "Sonde GetAppReviews (1 review, tri par mise à jour) des jeux dus -> "
        "raw.steam_review_counts : totaux, score et latest_timestamp_updated, le "
        "signal « a bougé » de l'incrémental. Chaque nuit les jeux qui bougent ou "
        "au-dessus de 1 000 reviews, une nuit par semaine les autres et les "
        "délistés (fiche retirée du store, is_delisted)."
    ),
)
def steam_review_counts(
    context: AssetExecutionContext,
    steam: SteamResource,
    clickhouse: ClickHouseResource,
) -> MaterializeResult:
    app_ids = [
        row["app_id"]
        for row in clickhouse.query(
            DUE_APP_IDS_SQL, {"hot_total_reviews": CENSUS_HOT_TOTAL_REVIEWS}
        )
    ]
    known = {row["app_id"] for row in clickhouse.query(KNOWN_APP_IDS_SQL)}
    delisted = {row["app_id"] for row in clickhouse.query(DELISTED_APP_IDS_SQL)}
    total = len(app_ids)
    context.log.info(
        f"Recensement de {total} jeux Steam dus ({CENSUS_WORKERS} workers, "
        f"lots de {CENSUS_BATCH_SIZE})"
    )

    probed = 0
    skipped = 0
    failed = 0
    newly_delisted = 0
    start = time.monotonic()

    def safe_probe(
        app_id: int,
    ) -> dict[str, Any] | None | Literal["delisted"] | Exception:
        try:
            return probe_or_delisted(steam, app_id, delisted)
        except (httpx.HTTPError, SteamApiError, ValueError) as exc:
            return exc

    with ThreadPoolExecutor(max_workers=CENSUS_WORKERS) as pool:
        for batch in itertools.batched(app_ids, CENSUS_BATCH_SIZE):
            probes = {}
            batch_delisted = []
            for app_id, result in zip(batch, pool.map(safe_probe, batch)):
                if isinstance(result, Exception):
                    failed += 1
                    context.log.warning(f"app_id={app_id}: sonde en échec ({result})")
                elif result == "delisted":
                    batch_delisted.append(app_id)
                # Sonde vide, fiche toujours en ligne : on garde l'ancien recensement.
                elif result is None:
                    skipped += 1
                else:
                    probes[app_id] = result
            new_delisted = [a for a in batch_delisted if a not in delisted]
            if new_delisted:
                context.log.info(f"Délistés (fiche retirée du store) : {new_delisted}")
            newly_delisted += len(new_delisted)
            write_census(clickhouse, probes, known, batch_delisted)
            delisted.difference_update(probes)
            delisted.update(batch_delisted)
            probed += len(batch)

            elapsed = time.monotonic() - start
            rate = probed / elapsed if elapsed > 0 else 0
            eta_min = (total - probed) / rate / 60 if rate > 0 else float("inf")
            context.log.info(
                f"Recensé {probed}/{total} ({probed / total:.0%}, {newly_delisted} "
                f"nouveaux délistés, {skipped} sans query_summary, {failed} en "
                f"échec) — {rate:.1f} jeux/s — "
                f"ETA {eta_min:.0f} min"
            )

    return MaterializeResult(
        metadata={
            "apps_probed": MetadataValue.int(probed),
            "apps_skipped": MetadataValue.int(skipped),
            "apps_newly_delisted": MetadataValue.int(newly_delisted),
            "apps_failed": MetadataValue.int(failed),
        }
    )
