import json
import time
from concurrent.futures import ThreadPoolExecutor

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from orchestration.resources import PostgresResource, SteamResource

ABSENT_STEAM_IDS = """
SELECT DISTINCT app_id FROM raw.steam_review_counts
WHERE last_backfill_at IS NULL OR last_backfill_at < NOW() - INTERVAL '1 month'
ORDER BY app_id ASC
"""

# Upsert : ne remplace la ligne que si la review est plus récente.
UPSERT_REVIEWS_SQL = """
INSERT INTO raw.steam_reviews (
    recommendation_id, app_id, payload, timestamp_created, timestamp_updated
)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (recommendation_id) DO UPDATE
SET payload           = EXCLUDED.payload,
    timestamp_created = EXCLUDED.timestamp_created,
    timestamp_updated = EXCLUDED.timestamp_updated,
    loaded_at         = now()
WHERE EXCLUDED.timestamp_updated > raw.steam_reviews.timestamp_updated;
"""

MARK_BACKFILLED_SQL = """
UPDATE raw.steam_review_counts
SET last_backfill_at = now()
WHERE app_id = %s;
"""

CENSUS_WORKERS = 5
CENSUS_BATCH_SIZE = 100


def fetch_steam_reviews(steam: SteamResource, app_id: int) -> list["dict"]:
    reviews: list["dict"] = []
    cursor = "*"
    while True:
        review_page = steam.get_all_reviews(app_id, cursor=cursor, language="all")
        if not review_page.get("reviews") or review_page["cursor"] == cursor:
            break
        else:
            reviews.extend(review_page["reviews"])
            cursor = review_page["cursor"]
    return reviews


@asset(
    group_name="load",
    deps=["steam_review_counts"],
    description="Backfill des reviews Steam (payload complet) -> raw.steam_reviews.",
)
def steam_reviews_backfill(
    context: AssetExecutionContext,
    steam: SteamResource,
    postgres: PostgresResource,
) -> MaterializeResult:
    app_ids = [row["app_id"] for row in postgres.fetch_all(ABSENT_STEAM_IDS)]
    total = len(app_ids)
    context.log.info(
        f"Backfill de {total} jeux Steam ({CENSUS_WORKERS} workers, "
        f"lots de {CENSUS_BATCH_SIZE})"
    )

    loaded = 0
    backfilled = 0
    start = time.monotonic()
    with (
        postgres.connect() as conn,
        ThreadPoolExecutor(max_workers=CENSUS_WORKERS) as pool,
    ):
        for batch_num, batch_start in enumerate(
            range(0, total, CENSUS_BATCH_SIZE), start=1
        ):
            batch = app_ids[batch_start : batch_start + CENSUS_BATCH_SIZE]
            reviews_by_app = pool.map(
                lambda app_id: fetch_steam_reviews(steam, app_id),
                batch,
            )
            rows = []
            for app_id, app_reviews in zip(batch, reviews_by_app):
                for review in app_reviews:
                    rows.append(
                        (
                            review["recommendationid"],
                            app_id,
                            json.dumps(review),
                            review["timestamp_created"],
                            review["timestamp_updated"],
                        )
                    )
            with conn.cursor() as cur:
                if rows:
                    cur.executemany(UPSERT_REVIEWS_SQL, rows)
                cur.executemany(MARK_BACKFILLED_SQL, [(app_id,) for app_id in batch])
            conn.commit()
            loaded += len(rows)
            backfilled += len(batch)
            elapsed = time.monotonic() - start
            rate = backfilled / elapsed if elapsed > 0 else 0
            eta_min = (total - backfilled) / rate / 60 if rate > 0 else float("inf")
            context.log.info(
                f"Backfillé {backfilled}/{total} ({backfilled / total:.0%}) "
                f"— {rate:.2f} jeux/s — {loaded} reviews chargées — ETA {eta_min:.0f} min"
            )
            if batch_num % 10 == 0:
                PAUSE_SECONDS = 120
                context.log.info(
                    f"Pause de {PAUSE_SECONDS}s après {batch_num} batches "
                    f"({backfilled} jeux traités)."
                )
                time.sleep(PAUSE_SECONDS)

    return MaterializeResult(metadata={"reviews_loaded": MetadataValue.int(loaded)})
