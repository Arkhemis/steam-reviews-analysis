import time
from concurrent.futures import ThreadPoolExecutor

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from orchestration.resources import PostgresResource, SteamResource


CENSUS_WORKERS = 8
CENSUS_BATCH_SIZE = 200

# On ne recense que les jeux liés à Steam.
SELECT_APP_IDS_SQL = """
SELECT DISTINCT steam_app_id AS app_id
FROM raw.igdb_games
WHERE steam_app_id IS NOT NULL;
"""

# Upsert : l'ancien total_reviews est copié dans prev_total_reviews.
UPSERT_COUNTS_SQL = """
INSERT INTO raw.steam_review_counts (
    app_id, total_reviews, total_positive, total_negative,
    review_score, review_score_desc, checked_at, prev_total_reviews
)
VALUES (%s, %s, %s, %s, %s, %s, now(), NULL)
ON CONFLICT (app_id) DO UPDATE
SET prev_total_reviews = raw.steam_review_counts.total_reviews,
    total_reviews      = EXCLUDED.total_reviews,
    total_positive     = EXCLUDED.total_positive,
    total_negative     = EXCLUDED.total_negative,
    review_score       = EXCLUDED.review_score,
    review_score_desc  = EXCLUDED.review_score_desc,
    checked_at         = now();
"""

INIT_FETCH_STATE_SQL = """
INSERT INTO raw.steam_fetch_state (app_id, backfill_status)
SELECT app_id, 'pending'
FROM raw.steam_review_counts
ON CONFLICT (app_id) DO NOTHING;
"""


@asset(
    group_name="ingest",
    deps=["igdb_games"],
    description="Sonde de recensement Steam (query_summary) par jeu -> raw.steam_review_counts.",
)
def steam_review_counts(
    context: AssetExecutionContext,
    steam: SteamResource,
    postgres: PostgresResource,
) -> MaterializeResult:
    app_ids = [row["app_id"] for row in postgres.fetch_all(SELECT_APP_IDS_SQL)]
    total = len(app_ids)
    context.log.info(
        f"Recensement de {total} jeux Steam ({CENSUS_WORKERS} workers, "
        f"lots de {CENSUS_BATCH_SIZE})"
    )

    probed = 0
    start = time.monotonic()
    with (
        postgres.connect() as conn,
        ThreadPoolExecutor(max_workers=CENSUS_WORKERS) as pool,
    ):
        for batch_start in range(0, total, CENSUS_BATCH_SIZE):
            batch = app_ids[batch_start : batch_start + CENSUS_BATCH_SIZE]
            summaries = pool.map(
                lambda app_id: steam.get_summary(app_id, language="french"), batch
            ) #TODO: change french after testing
            with conn.cursor() as cur:
                for app_id, summary in zip(batch, summaries):
                    cur.execute(
                        UPSERT_COUNTS_SQL,
                        (
                            app_id,
                            summary.get("total_reviews"),
                            summary.get("total_positive"),
                            summary.get("total_negative"),
                            summary.get("review_score"),
                            summary.get("review_score_desc"),
                        ),
                    )
            probed += len(batch)
            conn.commit()
            elapsed = time.monotonic() - start
            rate = probed / elapsed if elapsed > 0 else 0
            eta_min = (total - probed) / rate / 60 if rate > 0 else float("inf")
            context.log.info(
                f"Recensé {probed}/{total} ({probed / total:.0%}) "
                f"— {rate:.2f} jeux/s — ETA {eta_min:.0f} min"
            )

    return MaterializeResult(metadata={"apps_probed": MetadataValue.int(probed)})


@asset(
    group_name="ingest",
    deps=["steam_review_counts"],
    description="Initialise raw.steam_fetch_state (backfill_status='pending') pour les jeux recensés.",
)
def steam_fetch_state_init(
    context: AssetExecutionContext,
    postgres: PostgresResource,
) -> MaterializeResult:
    with postgres.connect() as conn:
        cur = conn.execute(INIT_FETCH_STATE_SQL)
        inserted = cur.rowcount
    context.log.info(f"steam_fetch_state : {inserted} nouvelles lignes 'pending'")
    return MaterializeResult(metadata={"rows_inserted": MetadataValue.int(inserted)})
