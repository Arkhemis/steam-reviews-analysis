import time
from concurrent.futures import ThreadPoolExecutor

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from orchestration.resources import PostgresResource, SteamResource

ABSENT_STEAM_IDS = """
SELECT DISTINCT app_id FROM raw.steam_review_counts
WHERE last_backfill_at IS NULL OR last_backfill_at < NOW() - INTERVAL '1 month'
"""

CENSUS_WORKERS = 5
CENSUS_BATCH_SIZE = 200


@asset(
    group_name="load",
    description="Sonde de recensement Steam (query_summary) par jeu -> raw.steam_review_counts.",
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
    with postgres.connect() as conn:
        pass