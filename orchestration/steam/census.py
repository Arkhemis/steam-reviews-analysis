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

# Le throttle Steam est global (~10 req/s, partagé avec le backfill et les
# annonces) : ce plafond vaut la durée max du run / 10. Régime stable ~40 000.
CENSUS_MAX_PROBES = 60000

# On ne recense que les jeux liés à Steam, et seulement ceux qui sont dus.
# `LIMIT NULL` = pas de plafond (full refresh).
DUE_APP_IDS_SQL = """
WITH steam_apps AS (
    SELECT DISTINCT steam_app_id AS app_id
    FROM raw.igdb_games
    WHERE steam_app_id IS NOT NULL
)
SELECT a.app_id, count(*) OVER () AS apps_due
FROM steam_apps AS a
LEFT JOIN raw.steam_review_counts AS c USING (app_id)
WHERE %(full_refresh)s
   OR c.app_id IS NULL
   -- Le backfill lit total_reviews pour sa tolérance d'arrêt : il le veut frais.
   OR c.last_backfill_at IS NULL
   OR c.total_reviews >= %(hot_total_reviews)s
   -- 16 h et pas 24 h : le run dure, un jeu sondé à sa fin n'aurait pas 24 h
   -- d'âge au run suivant. last_change_at NULL tombe dans le ELSE.
   OR c.checked_at < now() - CASE
        WHEN c.last_change_at > now() - interval '7 days'  THEN interval '16 hours'
        WHEN c.last_change_at > now() - interval '60 days' THEN interval '3 days'
        ELSE interval '14 days'
    END
-- Sous plafond, les jeux actifs d'abord : venant d'être sondés, un simple
-- ORDER BY checked_at les mettrait derrière toute la longue traîne.
ORDER BY CASE
        WHEN c.app_id IS NULL OR c.last_backfill_at IS NULL THEN 0
        WHEN c.total_reviews >= %(hot_total_reviews)s
             OR c.last_change_at > now() - interval '7 days' THEN 1
        ELSE 2
    END,
    c.checked_at ASC NULLS FIRST
LIMIT %(max_probes)s;
"""

# Upsert : l'ancien total_reviews est copié dans prev_total_reviews, et
# last_change_at n'avance que si le compteur a réellement bougé.
UPSERT_COUNTS_SQL = """
INSERT INTO raw.steam_review_counts (
    app_id, total_reviews, total_positive, total_negative,
    review_score, review_score_desc, checked_at, prev_total_reviews, last_change_at
)
VALUES (%s, %s, %s, %s, %s, %s, now(), NULL, now())
ON CONFLICT (app_id) DO UPDATE
SET prev_total_reviews = raw.steam_review_counts.total_reviews,
    total_reviews      = EXCLUDED.total_reviews,
    total_positive     = EXCLUDED.total_positive,
    total_negative     = EXCLUDED.total_negative,
    review_score       = EXCLUDED.review_score,
    review_score_desc  = EXCLUDED.review_score_desc,
    checked_at         = now(),
    last_change_at     = CASE
        WHEN EXCLUDED.total_reviews
             IS DISTINCT FROM raw.steam_review_counts.total_reviews
        THEN now()
        ELSE raw.steam_review_counts.last_change_at
    END;
"""


class SteamCensusConfig(Config):
    """Exposé dans le Launchpad : sonde tous les jeux, sans plafond ni fréquence."""

    full_refresh: bool = False


@asset(
    group_name="ingest",
    deps=["igdb_games"],
    description=(
        "Sonde de recensement Steam (query_summary) par jeu -> raw.steam_review_counts. "
        "Chaque jeu est sondé à une fréquence fonction de son activité, sauf full_refresh."
    ),
)
def steam_review_counts(
    context: AssetExecutionContext,
    config: SteamCensusConfig,
    steam: SteamResource,
    postgres: PostgresResource,
) -> MaterializeResult:
    due = postgres.fetch_all(
        DUE_APP_IDS_SQL,
        {
            "full_refresh": config.full_refresh,
            "hot_total_reviews": CENSUS_HOT_TOTAL_REVIEWS,
            "max_probes": None if config.full_refresh else CENSUS_MAX_PROBES,
        },
    )
    app_ids = [row["app_id"] for row in due]
    apps_due = due[0]["apps_due"] if due else 0
    total = len(app_ids)
    context.log.info(
        f"Recensement de {total} jeux Steam sur {apps_due} dus "
        f"({CENSUS_WORKERS} workers, lots de {CENSUS_BATCH_SIZE})"
    )
    if total < apps_due:
        context.log.warning(
            f"Plafond de {CENSUS_MAX_PROBES} sondes atteint : {apps_due - total} jeux "
            "reportés au prochain run (les jeux actifs passent d'abord)."
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

    return MaterializeResult(
        metadata={
            "apps_probed": MetadataValue.int(probed),
            "apps_due": MetadataValue.int(apps_due),
        }
    )
