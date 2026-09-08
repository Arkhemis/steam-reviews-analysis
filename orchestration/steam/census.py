import time
from concurrent.futures import ThreadPoolExecutor

from dagster import (
    AssetExecutionContext,
    Config,
    MaterializeResult,
    MetadataValue,
    asset,
)

from orchestration.postgres import PostgresResource
from orchestration.steam.resources import SteamResource


CENSUS_WORKERS = 8
CENSUS_BATCH_SIZE = 200

# Sondé chaque nuit même à compteur figé : une reprise d'activité ne doit pas
# attendre son tour sur un gros jeu.
CENSUS_HOT_TOTAL_REVIEWS = 1000

# On ne recense que les jeux liés à Steam, et seulement ceux qui sont dus :
# demander 173 000 fois par nuit à Steam « du neuf ? » coûte 5 h de run
# (throttle global ~10 req/s) pour 10 000 compteurs qui bougent.
DUE_APP_IDS_SQL = """
WITH steam_apps AS (
    SELECT DISTINCT steam_app_id AS app_id
    FROM raw.igdb_games
    WHERE steam_app_id IS NOT NULL
)
SELECT a.app_id
FROM steam_apps AS a
LEFT JOIN raw.steam_review_counts AS c USING (app_id)
WHERE %(full_refresh)s
   OR c.app_id IS NULL
   -- Le backfill lit total_reviews pour sa tolérance d'arrêt : il le veut frais.
   OR c.last_backfill_at IS NULL
   OR c.total_reviews >= %(hot_total_reviews)s
   -- A bougé à la sonde précédente : tant qu'un jeu vit, on le suit chaque nuit.
   OR c.total_reviews IS DISTINCT FROM c.prev_total_reviews
   -- Sinon une fois par semaine, à jour fixe par jeu : la longue traîne est
   -- étalée sur sept nuits au lieu de retomber d'un bloc.
   OR a.app_id %% 7 = extract(dow FROM now())::int
   -- Filet si une nuit a sauté : le jour fixe du jeu ne revient qu'en fin de semaine.
   OR c.checked_at < now() - interval '8 days';
"""

# Upsert : l'ancien total_reviews est copié dans prev_total_reviews, ce qui en
# fait le signal « a bougé » de la sonde suivante.
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


class SteamCensusConfig(Config):
    """Exposé dans le Launchpad : sonde tous les jeux, dus ou pas."""

    full_refresh: bool = False


@asset(
    group_name="ingest",
    deps=["igdb_games"],
    description=(
        "Sonde de recensement Steam (query_summary) par jeu -> raw.steam_review_counts. "
        "Chaque nuit les jeux qui bougent, une nuit par semaine les autres, "
        "sauf full_refresh."
    ),
)
def steam_review_counts(
    context: AssetExecutionContext,
    config: SteamCensusConfig,
    steam: SteamResource,
    postgres: PostgresResource,
) -> MaterializeResult:
    app_ids = [
        row["app_id"]
        for row in postgres.fetch_all(
            DUE_APP_IDS_SQL,
            {
                "full_refresh": config.full_refresh,
                "hot_total_reviews": CENSUS_HOT_TOTAL_REVIEWS,
            },
        )
    ]
    total = len(app_ids)
    context.log.info(
        f"Recensement de {total} jeux Steam dus ({CENSUS_WORKERS} workers, "
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
                lambda app_id: steam.get_summary(app_id, language="all"), batch
            )
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
