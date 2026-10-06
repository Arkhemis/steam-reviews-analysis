import itertools
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

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
           prev_total_reviews, checked_at
    FROM steam_review_counts
) AS counts USING (app_id)
WHERE counts.known IS NULL
   -- Le backfill lit total_reviews pour sa tolérance d'arrêt.
   OR last_backfill_at IS NULL
   OR total_reviews >= {hot_total_reviews:Int64}
   OR total_reviews IS DISTINCT FROM prev_total_reviews
   OR app_id % 7 = toDayOfWeek(now()) % 7
   -- Filet si une nuit a sauté.
   OR checked_at < now() - INTERVAL 8 DAY
   OR first_release_date BETWEEN today() - 7 AND today()
ORDER BY app_id
SETTINGS join_use_nulls = 1
"""

KNOWN_APP_IDS_SQL = "SELECT app_id FROM steam_review_counts"

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
    checked_at               = now64(6)
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


def write_census(
    clickhouse: ClickHouseResource, probes: dict[int, dict[str, Any]], known: set[int]
) -> None:
    if not probes:
        return
    new = [app_id for app_id in probes if app_id not in known]
    clickhouse.insert(
        "steam_review_counts",
        [(app_id, datetime.now(UTC)) for app_id in new],
        ["app_id", "checked_at"],
    )
    known.update(new)
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
        "au-dessus de 1 000 reviews, une nuit par semaine les autres."
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
    total = len(app_ids)
    context.log.info(
        f"Recensement de {total} jeux Steam dus ({CENSUS_WORKERS} workers, "
        f"lots de {CENSUS_BATCH_SIZE})"
    )

    probed = 0
    skipped = 0
    failed = 0
    start = time.monotonic()

    def safe_probe(app_id: int) -> dict[str, Any] | None | Exception:
        try:
            return probe(steam, app_id)
        except (httpx.HTTPError, SteamApiError, ValueError) as exc:
            return exc

    with ThreadPoolExecutor(max_workers=CENSUS_WORKERS) as pool:
        for batch in itertools.batched(app_ids, CENSUS_BATCH_SIZE):
            probes = {}
            for app_id, result in zip(batch, pool.map(safe_probe, batch)):
                if isinstance(result, Exception):
                    failed += 1
                    context.log.warning(f"app_id={app_id}: sonde en échec ({result})")
                # Steam renvoie parfois un 200 sans query_summary : on garde l'ancien recensement.
                elif result is None:
                    skipped += 1
                else:
                    probes[app_id] = result
            write_census(clickhouse, probes, known)
            probed += len(batch)

            elapsed = time.monotonic() - start
            rate = probed / elapsed if elapsed > 0 else 0
            eta_min = (total - probed) / rate / 60 if rate > 0 else float("inf")
            context.log.info(
                f"Recensé {probed}/{total} ({probed / total:.0%}, {skipped} sans "
                f"query_summary, {failed} en échec) — {rate:.1f} jeux/s — "
                f"ETA {eta_min:.0f} min"
            )

    return MaterializeResult(
        metadata={
            "apps_probed": MetadataValue.int(probed),
            "apps_skipped": MetadataValue.int(skipped),
            "apps_failed": MetadataValue.int(failed),
        }
    )
