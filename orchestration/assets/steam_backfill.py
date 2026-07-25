import json
from concurrent.futures import ThreadPoolExecutor

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from orchestration.resources import PostgresResource, SteamResource

ABSENT_STEAM_IDS = """
SELECT DISTINCT app_id FROM raw.steam_review_counts
WHERE last_backfill_at IS NULL OR last_backfill_at < NOW() - INTERVAL '1 month'
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

CENSUS_WORKERS = 5
CENSUS_BATCH_SIZE = 200


def fetch_steam_reviews(steam: SteamResource, app_id: int) -> list["dict"]:
    reviews: list["dict"] = []
    cursor = "*"
    while True:
        review_page = steam.get_all_reviews(
            app_id, cursor=cursor, language="french"
        )  # TODO: A retirer après les tests
        if not review_page.get("reviews") or review_page["cursor"] == cursor:
            break
        else:
            reviews.extend(review_page["reviews"])
            cursor = review_page["cursor"]
    return reviews


@asset(
    group_name="load",
    description="Backfill des reviews Steam (payload complet) -> raw.steam_reviews.",
)
def steam_review_counts(
    context: AssetExecutionContext,
    steam: SteamResource,
    postgres: PostgresResource,
) -> MaterializeResult:
    app_ids = [row["app_id"] for row in postgres.fetch_all(ABSENT_STEAM_IDS)]
    total = len(app_ids)
    context.log.info(
        f"Recensement de {total} jeux Steam ({CENSUS_WORKERS} workers, "
        f"lots de {CENSUS_BATCH_SIZE})"
    )

    loaded = 0
    with (
        postgres.connect() as conn,
        ThreadPoolExecutor(max_workers=CENSUS_WORKERS) as pool,
    ):
        for batch_start in range(0, total, CENSUS_BATCH_SIZE):
            batch = app_ids[batch_start : batch_start + CENSUS_BATCH_SIZE]
            reviews_by_app = pool.map(
                lambda app_id: fetch_steam_reviews(steam, app_id),
                batch,
            )
            with conn.cursor() as cur:
                for app_id, app_reviews in zip(batch, reviews_by_app):
                    for review in app_reviews:
                        cur.execute(
                            UPSERT_REVIEWS_SQL,
                            (
                                review["recommendationid"],
                                app_id,
                                json.dumps(review),
                                review["timestamp_created"],
                                review["timestamp_updated"],
                            ),
                        )
                        loaded += 1
            conn.commit()

    return MaterializeResult(metadata={"reviews_loaded": MetadataValue.int(loaded)})
