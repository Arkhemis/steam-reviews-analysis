import itertools
import json
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, NamedTuple

from dagster import (
    AssetExecutionContext,
    MaterializeResult,
    MetadataValue,
    asset,
    get_dagster_logger,
)

from orchestration.clickhouse import PARAM_BATCH_SIZE, ClickHouseResource
from orchestration.steam.backfill import (
    REVIEW_COLUMNS,
    STOP_BACKOFF_BASE_SECONDS,
    STOP_MAX_RETRIES,
    fetch_first_page,
    stop_tolerance,
)
from orchestration.steam.resources import SteamResource

INCREMENTAL_WORKERS = 3

# Reviews gardées en mémoire par jeu avant insertion.
FLUSH_REVIEWS = 5000
PROGRESS_EVERY = 500

# Checkpoint absent (jeu backfillé sans review) : 0 = pagination complète.
RELEVANT_APP_IDS = """
SELECT app_id,
       total_reviews,
       coalesce(last_seen_timestamp_updated, 0) AS last_seen_timestamp_updated
FROM steam_review_counts
WHERE last_backfill_at IS NOT NULL
  AND latest_timestamp_updated > coalesce(last_seen_timestamp_updated, 0)
"""

UPDATE_CHECKPOINT_SQL = """
UPDATE steam_review_counts
SET last_seen_timestamp_updated = greatest(
        coalesce(last_seen_timestamp_updated, 0),
        {max_timestamp_updated:Int64}
    )
WHERE app_id = {app_id:UInt32}
"""

# Sans FINAL : les doublons en attente de fusion ne changent pas un uniqExact.
STORED_COUNTS_SQL = """
SELECT c.app_id AS app_id,
       c.total_reviews_backfilled AS total_reviews_backfilled,
       ifNull(stored.reviews_stored, 0) AS reviews_stored
FROM steam_review_counts AS c
LEFT JOIN (
    SELECT app_id, uniqExact(recommendation_id) AS reviews_stored
    FROM steam_reviews
    GROUP BY app_id
) AS stored ON stored.app_id = c.app_id
WHERE c.last_backfill_at IS NOT NULL
SETTINGS final = 0, optimize_aggregation_in_order = 1, join_use_nulls = 1
"""

UPDATE_BACKFILLED_SQL = """
UPDATE steam_review_counts
SET total_reviews_backfilled = transform(
        app_id, {ids:Array(UInt32)}, {counts:Array(Int64)}, toInt64(0)
    )
WHERE app_id IN {ids:Array(UInt32)}
"""


class AppSync(NamedTuple):
    """Bilan de la synchronisation d'un jeu."""

    reviews_fetched: int
    versions_inserted: int
    reached_checkpoint: bool


@asset(
    group_name="load",
    # Sinon backfill et incrémental paginent le même jeu en parallèle.
    deps=["steam_review_counts", "steam_reviews_backfill"],
    description="Incremental backfill des reviews Steam (payload complet) -> raw.steam_reviews.",
)
def steam_reviews_incremental(
    context: AssetExecutionContext,
    steam: SteamResource,
    clickhouse: ClickHouseResource,
) -> MaterializeResult:
    relevant_apps = clickhouse.query(RELEVANT_APP_IDS)
    total = len(relevant_apps)
    context.log.info(
        f"Synchronisation incrémentale de {total} jeux Steam "
        f"({INCREMENTAL_WORKERS} workers, envoi au serveur tous les "
        f"{FLUSH_REVIEWS} reviews)"
    )

    reviews_fetched = 0
    review_versions_inserted = 0
    apps_updated = 0
    apps_incomplete = 0
    apps_failed = 0
    processed = 0

    with ThreadPoolExecutor(max_workers=INCREMENTAL_WORKERS) as pool:
        futures = {
            pool.submit(
                sync_app_reviews,
                steam,
                clickhouse,
                row["app_id"],
                row["last_seen_timestamp_updated"],
                row["total_reviews"],
            ): row["app_id"]
            for row in relevant_apps
        }
        for future in as_completed(futures):
            app_id = futures[future]
            processed += 1
            try:
                result = future.result()
            except Exception:
                apps_failed += 1
                context.log.exception(
                    f"app_id={app_id}: échec de la synchronisation, "
                    "checkpoint inchangé (repris au prochain run)"
                )
                continue

            reviews_fetched += result.reviews_fetched
            if not result.reached_checkpoint:
                apps_incomplete += 1
                continue

            review_versions_inserted += result.versions_inserted
            apps_updated += 1
            if result.versions_inserted:
                context.log.info(
                    f"app_id={app_id}: {result.versions_inserted} versions insérées"
                )
            if processed % PROGRESS_EVERY == 0:
                context.log.info(
                    f"Synchronisé {processed}/{total} jeux "
                    f"— {review_versions_inserted} versions insérées"
                )

    apps_recounted = recount_backfilled(clickhouse)
    context.log.info(
        f"total_reviews_backfilled recalculé depuis raw.steam_reviews "
        f"({apps_recounted} jeux corrigés)"
    )

    if apps_incomplete:
        context.log.warning(
            f"{apps_incomplete} jeux laissés incomplets (checkpoint non rejoint) : "
            "checkpoint inchangé, ils seront repris au prochain run."
        )

    return MaterializeResult(
        metadata={
            "reviews_fetched": MetadataValue.int(reviews_fetched),
            "review_versions_inserted": MetadataValue.int(review_versions_inserted),
            "apps_updated": MetadataValue.int(apps_updated),
            "apps_incomplete": MetadataValue.int(apps_incomplete),
            "apps_failed": MetadataValue.int(apps_failed),
            "apps_recounted": MetadataValue.int(apps_recounted),
        }
    )


class NewReviewPages:
    """Pages postérieures au checkpoint, servies une à une (`filter=updated` : tri décroissant)."""

    def __init__(
        self,
        steam: SteamResource,
        app_id: int,
        last_seen_timestamp_updated: int,
        total_reviews: int | None = None,
    ) -> None:
        self.steam = steam
        self.app_id = app_id
        self.last_seen_timestamp_updated = last_seen_timestamp_updated
        self.total_reviews = total_reviews
        self.has_checkpoint = last_seen_timestamp_updated > 0
        self.reached_checkpoint = False
        self.fetched = 0
        self.counted_cursor: str | None = None
        self.summary: dict[str, Any] | None = None

    def census_total_reached(self) -> bool:
        if self.total_reviews is None:
            return False
        return self.total_reviews - self.fetched <= stop_tolerance(self.total_reviews)

    def __iter__(self) -> Iterator[list[dict[str, Any]]]:
        logger = get_dagster_logger()
        cursor = "*"
        stop_retries = 0

        while True:
            # Le total du jour, plus frais que celui en base, sert de preuve d'arrêt.
            if cursor == "*" and self.summary is None and stop_retries == 0:
                review_page, self.summary = fetch_first_page(self.steam, self.app_id)
                if self.summary is not None:
                    self.total_reviews = self.summary["total_reviews"]
            else:
                review_page = self.steam.get_all_reviews(
                    self.app_id, cursor=cursor, language="all"
                )
            reviews = review_page.get("reviews") or []
            next_cursor = review_page.get("cursor")

            page: list[dict[str, Any]] = []
            passed_checkpoint = False
            for review in reviews:
                # Égalités gardées : même seconde que le checkpoint, dédupliquées ensuite.
                if review["timestamp_updated"] < self.last_seen_timestamp_updated:
                    logger.info(
                        f"app_id={self.app_id}: pagination arrêtée au checkpoint "
                        f"timestamp_updated={self.last_seen_timestamp_updated}"
                    )
                    self.reached_checkpoint = True
                    passed_checkpoint = True
                    break
                if review["timestamp_updated"] == self.last_seen_timestamp_updated:
                    self.reached_checkpoint = True
                page.append(review)

            # Une page rejouée ne compte qu'une fois.
            if reviews and cursor != self.counted_cursor:
                self.fetched += len(reviews)
                self.counted_cursor = cursor

            stalled = not reviews or not next_cursor or next_cursor == cursor
            give_up = stalled and stop_retries >= STOP_MAX_RETRIES
            # Sans checkpoint, le total recensé fait preuve d'arrêt.
            if stalled and not self.has_checkpoint and self.census_total_reached():
                self.reached_checkpoint = True
            # Avec checkpoint, seul le total complet le prouve : toutes les reviews sont plus récentes.
            if stalled and self.fetched >= (self.total_reviews or float("inf")):
                self.reached_checkpoint = True

            if page and (self.reached_checkpoint or not stalled or give_up):
                yield page
            if passed_checkpoint:
                return

            if stalled:
                if self.reached_checkpoint:
                    return
                # Steam annonce souvent de fausses fins : on rejoue le même curseur.
                if give_up:
                    if not self.has_checkpoint:
                        self.reached_checkpoint = True
                        return
                    logger.warning(
                        f"app_id={self.app_id}: checkpoint non rejoint après "
                        f"{STOP_MAX_RETRIES} relances du curseur"
                    )
                    return
                stop_retries += 1
                delay = STOP_BACKOFF_BASE_SECONDS * 2 ** (stop_retries - 1)
                logger.warning(
                    f"app_id={self.app_id}: fin prématurée avant le checkpoint ; "
                    f"relance du même curseur {stop_retries}/{STOP_MAX_RETRIES} "
                    f"dans {delay:.0f}s"
                )
                time.sleep(delay)
                continue

            stop_retries = 0
            cursor = next_cursor


def iter_review_batches(
    pages: Iterable[list[dict[str, Any]]], size: int
) -> Iterator[list[dict[str, Any]]]:
    """Regroupe les pages en lots d'au moins `size` reviews."""
    batch: list[dict[str, Any]] = []
    for page in pages:
        batch.extend(page)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def sync_app_reviews(
    steam: SteamResource,
    clickhouse: ClickHouseResource,
    app_id: int,
    last_seen_timestamp_updated: int,
    total_reviews: int | None = None,
) -> AppSync:
    """Le checkpoint n'avance qu'après les insertions ; raw déduplique ce qu'une relance réinsère."""
    logger = get_dagster_logger()
    pages = NewReviewPages(steam, app_id, last_seen_timestamp_updated, total_reviews)
    fetched = 0
    versions_inserted = 0
    max_timestamp_updated = last_seen_timestamp_updated

    for batch in iter_review_batches(pages, FLUSH_REVIEWS):
        fetched += len(batch)
        max_timestamp_updated = max(
            max_timestamp_updated,
            max(review["timestamp_updated"] for review in batch),
        )
        versions_inserted += insert_versions(clickhouse, app_id, batch)

    if not pages.reached_checkpoint:
        logger.warning(f"app_id={app_id}: checkpoint non atteint")
        return AppSync(fetched, 0, False)

    clickhouse.command(
        UPDATE_CHECKPOINT_SQL,
        {"app_id": app_id, "max_timestamp_updated": max_timestamp_updated},
    )
    return AppSync(fetched, versions_inserted, True)


def insert_versions(
    clickhouse: ClickHouseResource, app_id: int, reviews: list[dict[str, Any]]
) -> int:
    """Sans lecture préalable : seule la seconde du checkpoint peut doublonner, et raw déduplique."""
    if not reviews:
        return 0

    # Steam resert parfois une review d'une page à l'autre.
    versions = {
        (int(review["recommendationid"]), review["timestamp_updated"]): review
        for review in reviews
    }
    rows = [review_to_row(app_id, review) for review in versions.values()]
    clickhouse.insert("steam_reviews", rows, REVIEW_COLUMNS)
    return len(rows)


def recount_backfilled(clickhouse: ClickHouseResource) -> int:
    """Réaligne total_reviews_backfilled sur raw.steam_reviews ; renvoie le nombre de jeux corrigés."""
    drifted = [
        (row["app_id"], row["reviews_stored"])
        for row in clickhouse.query(STORED_COUNTS_SQL)
        if row["total_reviews_backfilled"] != row["reviews_stored"]
    ]
    for batch in itertools.batched(drifted, PARAM_BATCH_SIZE):
        ids, counts = zip(*batch)
        clickhouse.command(
            UPDATE_BACKFILLED_SQL, {"ids": list(ids), "counts": list(counts)}
        )
    return len(drifted)


def review_to_row(app_id: int, review: dict[str, Any]) -> tuple:
    return (
        int(review["recommendationid"]),
        app_id,
        json.dumps(review),
        review["timestamp_created"],
        review["timestamp_updated"],
    )
