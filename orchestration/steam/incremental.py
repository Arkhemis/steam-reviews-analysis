import json
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

from dagster import (
    AssetExecutionContext,
    MaterializeResult,
    MetadataValue,
    asset,
    get_dagster_logger,
)

from orchestration.postgres import PostgresResource
from orchestration.steam.resources import SteamResource


RELEVANT_APP_IDS = """
SELECT app_id, last_seen_timestamp_updated
FROM raw.steam_review_counts
WHERE COALESCE(total_reviews_backfilled, 0) < total_reviews
  AND last_seen_timestamp_updated IS NOT NULL
"""

INSERT_REVIEW_SQL = """
INSERT INTO raw.steam_reviews (
    recommendation_id, app_id, payload, timestamp_created, timestamp_updated
)
VALUES (%s, %s, %s, %s, %s)
"""

EXISTING_REVIEW_VERSIONS_SQL = """
SELECT recommendation_id, timestamp_updated
FROM raw.steam_reviews
WHERE app_id = %s
  AND recommendation_id = ANY(%s)
"""

UPDATE_REVIEW_COUNT_SQL = """
UPDATE raw.steam_review_counts
SET total_reviews_backfilled = LEAST(
        total_reviews,
        COALESCE(total_reviews_backfilled, 0) + %s
    ),
    last_seen_timestamp_updated = GREATEST(
        COALESCE(last_seen_timestamp_updated, 0),
        %s
    )
WHERE app_id = %s
"""


@asset(
    group_name="load",
    deps=["steam_review_counts"],
    description="Incremental backfill des reviews Steam (payload complet) -> raw.steam_reviews.",
)
def steam_reviews_incremental(
    context: AssetExecutionContext,
    steam: SteamResource,
    postgres: PostgresResource,
) -> MaterializeResult:
    logger = get_dagster_logger()
    logger.info("Starting incremental backfill of Steam reviews")

    relevant_apps = postgres.fetch_all(RELEVANT_APP_IDS)
    apps_by_id = {row["app_id"]: row for row in relevant_apps}
    reviews_fetched = 0
    review_versions_inserted = 0
    apps_updated = 0
    apps_incomplete = 0

    with (
        postgres.connect() as conn,
        ThreadPoolExecutor(max_workers=10) as pool,
    ):
        futures = {
            pool.submit(
                fetch_steam_reviews,
                steam,
                row["app_id"],
                row["last_seen_timestamp_updated"],
            ): row
            for row in relevant_apps
        }
        for future in as_completed(futures):
            app = futures[future]
            app_id = app["app_id"]
            reviews, reached_checkpoint = future.result()
            reviews_fetched += len(reviews)

            if not reached_checkpoint:
                apps_incomplete += 1
                logger.warning(
                    f"app_id={app_id}: checkpoint non atteint ; "
                    "aucune donnée enregistrée"
                )
                continue

            recommendation_ids = list(
                {review["recommendationid"] for review in reviews}
            )
            existing_versions: set[tuple[int, int]] = set()
            existing_recommendation_ids: set[int] = set()
            if recommendation_ids:
                with conn.cursor() as cur:
                    cur.execute(
                        EXISTING_REVIEW_VERSIONS_SQL,
                        (app_id, recommendation_ids),
                    )
                    for row in cur.fetchall():
                        existing_versions.add(
                            (row["recommendation_id"], row["timestamp_updated"])
                        )
                        existing_recommendation_ids.add(row["recommendation_id"])

            reviews_to_insert = [
                review
                for review in reviews
                if (
                    review["recommendationid"],
                    review["timestamp_updated"],
                )
                not in existing_versions
            ]
            new_review_count = len(
                set(recommendation_ids) - existing_recommendation_ids
            )
            max_timestamp_updated = max(
                (review["timestamp_updated"] for review in reviews),
                default=apps_by_id[app_id]["last_seen_timestamp_updated"],
            )

            with conn.cursor() as cur:
                if reviews_to_insert:
                    cur.executemany(
                        INSERT_REVIEW_SQL,
                        reviews_to_rows(app_id, reviews_to_insert),
                    )
                cur.execute(
                    UPDATE_REVIEW_COUNT_SQL,
                    (new_review_count, max_timestamp_updated, app_id),
                )
            conn.commit()

            review_versions_inserted += len(reviews_to_insert)
            apps_updated += 1
            logger.info(
                f"app_id={app_id}: {len(reviews_to_insert)} versions insérées, "
                f"dont {new_review_count} nouvelles reviews"
            )

    return MaterializeResult(
        metadata={
            "reviews_fetched": MetadataValue.int(reviews_fetched),
            "review_versions_inserted": MetadataValue.int(review_versions_inserted),
            "apps_updated": MetadataValue.int(apps_updated),
            "apps_incomplete": MetadataValue.int(apps_incomplete),
        }
    )


def fetch_steam_reviews(
    steam: SteamResource,
    app_id: int,
    last_seen_timestamp_updated: int,
) -> tuple[list["dict"], bool]:
    """Renvoie les versions récentes et indique si le checkpoint a été atteint.

    Les pages sont écrites au fur et à mesure sur un fichier temporaire plutôt
    que dans une liste en mémoire : un jeu dont le checkpoint est ancien peut
    nécessiter des milliers de pages avant de s'arrêter, et jusqu'à dix jeux
    sont récupérés en parallèle. Le fichier est supprimé automatiquement à la
    sortie du `with`, que le checkpoint ait été atteint ou non.
    """
    logger = get_dagster_logger()
    cursor = "*"
    saw_checkpoint_timestamp = last_seen_timestamp_updated == 0

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as spool:

        def load_spooled() -> list["dict"]:
            spool.seek(0)
            return [json.loads(line) for line in spool]

        while True:
            review_page = steam.get_all_reviews(app_id, cursor=cursor, language="all")
            reviews = review_page.get("reviews") or []
            next_cursor = review_page.get("cursor")

            if not reviews:
                return load_spooled(), saw_checkpoint_timestamp

            for review in reviews:
                # On inclut les égalités afin de ne pas perdre une review publiée
                # dans la même seconde que le checkpoint. Elles seront dédupliquées
                # par (recommendation_id, timestamp_updated) avant insertion.
                if review["timestamp_updated"] < last_seen_timestamp_updated:
                    logger.info(
                        f"app_id={app_id}: pagination arrêtée au checkpoint "
                        f"timestamp_updated={last_seen_timestamp_updated}"
                    )
                    return load_spooled(), True
                if review["timestamp_updated"] == last_seen_timestamp_updated:
                    saw_checkpoint_timestamp = True
                spool.write(json.dumps(review) + "\n")

            if not next_cursor or next_cursor == cursor:
                return load_spooled(), saw_checkpoint_timestamp
            cursor = next_cursor


def reviews_to_rows(app_id: int, reviews: list["dict"]) -> list[tuple]:
    return [
        (
            review["recommendationid"],
            app_id,
            json.dumps(review),
            review["timestamp_created"],
            review["timestamp_updated"],
        )
        for review in reviews
    ]
