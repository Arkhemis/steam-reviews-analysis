import json
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx
from clickhouse_connect.driver.exceptions import ClickHouseError
from dagster import (
    AssetExecutionContext,
    MaterializeResult,
    MetadataValue,
    asset,
    get_dagster_logger,
)

from orchestration.clickhouse import ClickHouseResource
from orchestration.steam.resources import SteamApiError, SteamResource

HEAVY_REVIEW_THRESHOLD = 10000
HEAVY_PAGE_FLUSH_INTERVAL = 1000


# Le total recensé inclut des reviews que le listing ne sert jamais (~11 % sur les jeux chinois).
STOP_TOLERANCE_RATIO = 0.15
STOP_TOLERANCE_MIN = 50
STOP_MAX_RETRIES = 6
STOP_BACKOFF_BASE_SECONDS = 5.0
# Relances de la page 1 quand Steam omet son query_summary.
SUMMARY_RETRIES = 2


def stop_tolerance(total_reviews: int | None) -> int:
    return max(STOP_TOLERANCE_MIN, int((total_reviews or 0) * STOP_TOLERANCE_RATIO))


ABSENT_STEAM_IDS = """
SELECT app_id, total_reviews FROM steam_review_counts
WHERE last_backfill_at IS NULL AND NOT is_delisted
ORDER BY total_reviews ASC NULLS FIRST
"""

REVIEW_COLUMNS = [
    "recommendation_id",
    "app_id",
    "payload",
    "timestamp_created",
    "timestamp_updated",
]

# Les SET lisent tous les valeurs d'avant l'UPDATE.
MARK_BACKFILLED_SQL = """
UPDATE steam_review_counts
SET last_backfill_at = now64(6),
    total_reviews_backfilled = transform(
        app_id, {ids:Array(UInt32)}, {fetched:Array(Int64)}, toInt64(0)
    ),
    last_seen_timestamp_updated = greatest(
        coalesce(last_seen_timestamp_updated, 0),
        transform(app_id, {ids:Array(UInt32)}, {max_ts:Array(Int64)}, toInt64(0))
    )
WHERE app_id IN {ids:Array(UInt32)}
"""


def mark_backfilled(
    clickhouse: ClickHouseResource, marks: list[tuple[int, int, int]]
) -> None:
    """Marque les jeux backfillés : (app_id, reviews chargées, max timestamp_updated)."""
    if not marks:
        return
    ids, fetched, max_ts = zip(*marks)
    clickhouse.command(
        MARK_BACKFILLED_SQL,
        {"ids": list(ids), "fetched": list(fetched), "max_ts": list(max_ts)},
    )


def insert_reviews(clickhouse: ClickHouseResource, rows: list[tuple]) -> None:
    clickhouse.insert("steam_reviews", rows, REVIEW_COLUMNS)


def fetch_first_page(
    steam: SteamResource, app_id: int
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Rejoue la page 1 quand Steam omet le query_summary, sans quoi pas de garde-fou d'arrêt."""
    for _ in range(SUMMARY_RETRIES + 1):
        review_page = steam.get_all_reviews(app_id, cursor="*", language="all")
        summary = review_page.get("query_summary") or {}
        if summary.get("total_reviews") is not None:
            return review_page, summary
    get_dagster_logger().warning(
        f"app_id={app_id}: page 1 sans query_summary après {SUMMARY_RETRIES} relances"
    )
    return review_page, None


CENSUS_WORKERS = 5
CENSUS_BATCH_SIZE = 100


class ReviewPages:
    """Rejoue le même curseur tant qu'un signal de fin laisse un écart au total > `stop_tolerance`."""

    def __init__(
        self, steam: SteamResource, app_id: int, total_reviews: int | None
    ) -> None:
        self.steam = steam
        self.app_id = app_id
        self.total_reviews = total_reviews
        self.summary: dict[str, Any] | None = None
        self.complete = False

    def __iter__(self) -> Iterator[list[dict[str, Any]]]:
        logger = get_dagster_logger()
        app_id = self.app_id
        cursor = "*"
        fetched = 0
        stop_retries = 0
        while True:
            if cursor == "*" and self.summary is None and stop_retries == 0:
                review_page, self.summary = fetch_first_page(self.steam, app_id)
                if self.summary is not None:
                    self.total_reviews = self.summary["total_reviews"]
            else:
                review_page = self.steam.get_all_reviews(
                    app_id, cursor=cursor, language="all"
                )
            total_reviews = self.total_reviews
            reviews = review_page.get("reviews") or []
            next_cursor = review_page.get("cursor")

            if not reviews or not next_cursor or next_cursor == cursor:
                missing = (total_reviews or 0) - fetched
                if total_reviews is None:
                    return
                if missing <= stop_tolerance(total_reviews):
                    self.complete = True
                    return
                if stop_retries >= STOP_MAX_RETRIES:
                    logger.warning(
                        f"app_id={app_id}: pagination abandonnée à {fetched}/{total_reviews} "
                        f"reviews ({missing} manquantes) après {STOP_MAX_RETRIES} relances"
                    )
                    return
                stop_retries += 1
                delay = STOP_BACKOFF_BASE_SECONDS * 2 ** (stop_retries - 1)
                logger.warning(
                    f"app_id={app_id}: fin prématurée à {fetched}/{total_reviews} reviews "
                    f"({missing} manquantes) ; relance du même curseur "
                    f"{stop_retries}/{STOP_MAX_RETRIES} dans {delay:.0f}s"
                )
                time.sleep(delay)
                continue

            stop_retries = 0
            fetched += len(reviews)
            cursor = next_cursor
            yield reviews


def fetch_steam_reviews(
    steam: SteamResource, app_id: int, total_reviews: int | None
) -> tuple[list[dict[str, Any]], ReviewPages]:
    pages = ReviewPages(steam, app_id, total_reviews)
    return [review for page in pages for review in page], pages


def reviews_to_rows(app_id: int, reviews: list["dict"]) -> list[tuple]:
    return [
        (
            int(review["recommendationid"]),
            app_id,
            json.dumps(review),
            review["timestamp_created"],
            review["timestamp_updated"],
        )
        for review in reviews
    ]


def backfill_heavy_app_id(
    steam: SteamResource,
    clickhouse: ClickHouseResource,
    context: AssetExecutionContext,
    app_id: int,
    total_reviews: int | None,
) -> tuple[int, bool]:
    """Renvoie (reviews chargées, backfill complet)."""
    fetched = 0
    max_ts = 0
    pending_rows: list[tuple] = []
    pages_since_flush = 0
    pages = ReviewPages(steam, app_id, total_reviews)
    for reviews in pages:
        for review in reviews:
            max_ts = max(max_ts, review["timestamp_updated"])
        pending_rows.extend(reviews_to_rows(app_id, reviews))
        fetched += len(reviews)
        pages_since_flush += 1
        if pages_since_flush >= HEAVY_PAGE_FLUSH_INTERVAL:
            insert_reviews(clickhouse, pending_rows)
            pending_rows = []
            pages_since_flush = 0
    insert_reviews(clickhouse, pending_rows)

    total_reviews = pages.total_reviews
    if not pages.complete:
        context.log.warning(
            f"[volumineux] app_id={app_id}: {fetched}/{total_reviews} reviews "
            "seulement, last_backfill_at laissé NULL (sera retenté au prochain run)"
        )
        return fetched, False

    # En dernier : un arrêt avant fait rejouer le jeu, et raw déduplique.
    mark_backfilled(clickhouse, [(app_id, fetched, max_ts)])
    context.log.info(f"[volumineux] app_id={app_id}: {fetched} reviews chargées")
    return fetched, True


@asset(
    group_name="load",
    deps=["steam_review_counts"],
    description="Backfill des reviews Steam (payload complet) -> raw.steam_reviews.",
)
def steam_reviews_backfill(
    context: AssetExecutionContext,
    steam: SteamResource,
    clickhouse: ClickHouseResource,
) -> MaterializeResult:
    rows = clickhouse.query(ABSENT_STEAM_IDS)
    zero_ids: list[int] = []
    light_apps: list[tuple[int, int | None]] = []
    heavy_apps: list[tuple[int, int | None]] = []
    for row in rows:
        total_reviews = row["total_reviews"]
        if total_reviews == 0:
            zero_ids.append(row["app_id"])
        elif (total_reviews or 0) > HEAVY_REVIEW_THRESHOLD:
            heavy_apps.append((row["app_id"], total_reviews))
        else:
            light_apps.append((row["app_id"], total_reviews))

    total = len(zero_ids) + len(light_apps) + len(heavy_apps)
    context.log.info(
        f"Backfill de {total} jeux Steam : {len(zero_ids)} sans review "
        f"(total_reviews=0, marqués sans appel API), {len(light_apps)} légers "
        f"(lots de {CENSUS_BATCH_SIZE}, {CENSUS_WORKERS} workers) et "
        f"{len(heavy_apps)} volumineux (> {HEAVY_REVIEW_THRESHOLD} reviews, "
        f"traités un par un avec pagination streamée)"
    )

    loaded = 0
    backfilled = 0
    incomplete = 0
    start = time.monotonic()

    if zero_ids:
        mark_backfilled(clickhouse, [(app_id, 0, 0) for app_id in zero_ids])
        backfilled += len(zero_ids)
        context.log.info(
            f"[sans review] {len(zero_ids)} jeux marqués backfillés directement, "
            "0 appel API."
        )

    with ThreadPoolExecutor(max_workers=CENSUS_WORKERS) as pool:
        for batch_num, batch_start in enumerate(
            range(0, len(light_apps), CENSUS_BATCH_SIZE), start=1
        ):
            batch = light_apps[batch_start : batch_start + CENSUS_BATCH_SIZE]
            reviews_by_app = pool.map(
                lambda app: fetch_steam_reviews(steam, app[0], app[1]),
                batch,
            )
            batch_rows = []
            marks = []
            for (app_id, _), (app_reviews, pages) in zip(batch, reviews_by_app):
                app_total = pages.total_reviews
                if not pages.complete:
                    incomplete += 1
                    context.log.warning(
                        f"[léger] app_id={app_id}: {len(app_reviews)}/{app_total} "
                        "reviews seulement, ignoré et last_backfill_at laissé NULL "
                        "(sera retenté au prochain run)"
                    )
                    continue
                batch_rows.extend(reviews_to_rows(app_id, app_reviews))
                app_max_ts = max(
                    (r["timestamp_updated"] for r in app_reviews), default=0
                )
                marks.append((app_id, len(app_reviews), app_max_ts))
            # Marquage en dernier : un arrêt fait rejouer le lot.
            insert_reviews(clickhouse, batch_rows)
            mark_backfilled(clickhouse, marks)
            loaded += len(batch_rows)
            backfilled += len(marks)
            elapsed = time.monotonic() - start
            rate = backfilled / elapsed if elapsed > 0 else 0
            eta_min = (total - backfilled) / rate / 60 if rate > 0 else float("inf")
            context.log.info(
                f"[léger] Backfillé {backfilled}/{total} ({backfilled / total:.0%}) "
                f"— {rate:.2f} jeux/s — {loaded} reviews chargées — ETA {eta_min:.0f} min"
            )
            if batch_num % 10 == 0:
                PAUSE_SECONDS = 120
                context.log.info(
                    f"Pause de {PAUSE_SECONDS}s après {batch_num} batches "
                    f"({backfilled} jeux traités)."
                )
                time.sleep(PAUSE_SECONDS)

    with ThreadPoolExecutor(max_workers=CENSUS_WORKERS) as pool:
        futures = {
            pool.submit(
                backfill_heavy_app_id, steam, clickhouse, context, app_id, total_reviews
            ): app_id
            for app_id, total_reviews in heavy_apps
        }
        for future in as_completed(futures):
            app_id = futures[future]
            try:
                app_loaded, complete = future.result()
            except (httpx.HTTPError, SteamApiError, ValueError, ClickHouseError):
                context.log.error(
                    f"[volumineux] app_id={app_id}: échec, sera retenté au "
                    "prochain run (last_backfill_at non mis à jour)"
                )
                continue
            loaded += app_loaded
            if not complete:
                incomplete += 1
                continue
            backfilled += 1
            elapsed = time.monotonic() - start
            rate = backfilled / elapsed if elapsed > 0 else 0
            eta_min = (total - backfilled) / rate / 60 if rate > 0 else float("inf")
            context.log.info(
                f"[volumineux] Backfillé {backfilled}/{total} ({backfilled / total:.0%}) "
                f"— {loaded} reviews chargées — ETA {eta_min:.0f} min"
            )

    if incomplete:
        context.log.warning(
            f"{incomplete} jeux laissés incomplets (pagination Steam arrêtée trop "
            "tôt malgré les relances) : non marqués, ils seront repris au "
            "prochain run."
        )

    return MaterializeResult(
        metadata={
            "reviews_loaded": MetadataValue.int(loaded),
            "apps_backfilled": MetadataValue.int(backfilled),
            "apps_incomplete": MetadataValue.int(incomplete),
        }
    )
