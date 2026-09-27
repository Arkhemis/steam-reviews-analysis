import json
import time
from collections.abc import Iterator
from typing import Any
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

# Au-delà de ce volume, un jeu est considéré comme "big"
HEAVY_REVIEW_THRESHOLD = 10000

# Pour les jeux volumineux, on upsert/commit tous les N pages Steam
HEAVY_PAGE_FLUSH_INTERVAL = 1000


# Le recensement compte des reviews que l'endpoint de listing ne sert jamais
# (jusqu'à ~11% sur les jeux à reviews majoritairement chinoises) : tolérance
# relative, avec plancher pour les petits jeux.
STOP_TOLERANCE_RATIO = 0.15
STOP_TOLERANCE_MIN = 50
STOP_MAX_RETRIES = 6
STOP_BACKOFF_BASE_SECONDS = 5.0
# Relances de la page 1 quand Steam omet son query_summary.
SUMMARY_RETRIES = 2


def stop_tolerance(total_reviews: int | None) -> int:
    return max(STOP_TOLERANCE_MIN, int((total_reviews or 0) * STOP_TOLERANCE_RATIO))


# Un jeu apparu au recensement GetItems n'a pas encore de total : son compteur
# Steam (sans les clés) sert d'ordre de grandeur pour le classer.
ABSENT_STEAM_IDS = """
SELECT app_id, total_reviews, steam_count FROM raw.steam_review_counts
WHERE last_backfill_at IS NULL
ORDER BY COALESCE(total_reviews, steam_count) ASC NULLS FIRST
"""

INSERT_REVIEWS_SQL = """
INSERT INTO raw.steam_reviews (
    recommendation_id, app_id, payload, timestamp_created, timestamp_updated
)
VALUES (%s, %s, %s, %s, %s);
"""

MARK_BACKFILLED_SQL = """
UPDATE raw.steam_review_counts
SET last_backfill_at = now(),
    total_reviews_backfilled = %s,
    last_seen_timestamp_updated = GREATEST(
        COALESCE(last_seen_timestamp_updated, 0),
        %s
    ),
    synced_steam_count = steam_count
WHERE app_id = %s;
"""

# Totaux de la page 1 de /appreviews, écrits même si la pagination échoue :
# ils restent vrais, et servent de garde-fou d'arrêt au run suivant.
UPDATE_SUMMARY_SQL = """
UPDATE raw.steam_review_counts
SET prev_total_reviews = total_reviews,
    total_reviews      = %s,
    total_positive     = %s,
    total_negative     = %s,
    review_score       = %s,
    review_score_desc  = %s,
    checked_at         = now()
WHERE app_id = %s;
"""


def fetch_first_page(
    steam: SteamResource, app_id: int
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Page 1 et son query_summary (mêmes champs que l'ancien recensement).

    Steam omet parfois le résumé : la page est rejouée, puisque sans total le
    garde-fou contre les fausses fins de pagination est désactivé.
    """
    for _ in range(SUMMARY_RETRIES + 1):
        review_page = steam.get_all_reviews(app_id, cursor="*", language="all")
        summary = review_page.get("query_summary") or {}
        if summary.get("total_reviews") is not None:
            return review_page, summary
    get_dagster_logger().warning(
        f"app_id={app_id}: page 1 sans query_summary après {SUMMARY_RETRIES} relances"
    )
    return review_page, None


def summary_params(app_id: int, summary: dict[str, Any]) -> tuple:
    return (
        summary.get("total_reviews"),
        summary.get("total_positive"),
        summary.get("total_negative"),
        summary.get("review_score"),
        summary.get("review_score_desc"),
        app_id,
    )


CENSUS_WORKERS = 5
CENSUS_BATCH_SIZE = 100


class ReviewPages:
    """Pagine les reviews d'un jeu en résistant aux faux signaux de fin de Steam.

    Tant que l'écart au total de la page 1 (à défaut, au dernier connu) dépasse
    `stop_tolerance`, un signal de fin est considéré comme un incident
    transitoire : on rejoue le même curseur après un backoff exponentiel.
    """

    def __init__(
        self, steam: SteamResource, app_id: int, total_reviews: int | None
    ) -> None:
        self.steam = steam
        self.app_id = app_id
        self.total_reviews = total_reviews
        self.summary: dict[str, Any] | None = None
        # Vrai seulement si la fin est confirmée par un total connu.
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
            review["recommendationid"],
            app_id,
            json.dumps(review),
            review["timestamp_created"],
            review["timestamp_updated"],
        )
        for review in reviews
    ]


def backfill_heavy_app_id(
    steam: SteamResource,
    postgres: PostgresResource,
    context: AssetExecutionContext,
    app_id: int,
    total_reviews: int | None,
) -> tuple[int, bool]:
    """Pagine et upsert un jeu volumineux page par page, en envoyant les lignes au
    serveur tous les HEAVY_PAGE_FLUSH_INTERVAL pages pour ne jamais garder tout le
    jeu en mémoire.

    Renvoie (reviews chargées, backfill complet). Le commit n'a lieu qu'à la fin.
    """
    fetched = 0
    max_ts = 0
    pending_rows: list[tuple] = []
    pages_since_flush = 0
    pages = ReviewPages(steam, app_id, total_reviews)
    with postgres.connect() as conn:
        for reviews in pages:
            for review in reviews:
                max_ts = max(max_ts, review["timestamp_updated"])
            pending_rows.extend(reviews_to_rows(app_id, reviews))
            fetched += len(reviews)
            pages_since_flush += 1
            if pages_since_flush >= HEAVY_PAGE_FLUSH_INTERVAL:
                # Envoyé au serveur mais pas commité : la mémoire du process est
                # libérée sans renoncer à pouvoir tout annuler.
                with conn.cursor() as cur:
                    cur.executemany(INSERT_REVIEWS_SQL, pending_rows)
                pending_rows = []
                pages_since_flush = 0

        if pending_rows:
            with conn.cursor() as cur:
                cur.executemany(INSERT_REVIEWS_SQL, pending_rows)

        total_reviews = pages.total_reviews
        if not pages.complete:
            conn.rollback()
            if pages.summary is not None:
                with conn.cursor() as cur:
                    cur.execute(
                        UPDATE_SUMMARY_SQL, summary_params(app_id, pages.summary)
                    )
                conn.commit()
            context.log.warning(
                f"[volumineux] app_id={app_id}: {fetched}/{total_reviews} reviews "
                "seulement, insertion annulée et last_backfill_at laissé NULL "
                "(sera retenté au prochain run)"
            )
            return 0, False

        with conn.cursor() as cur:
            if pages.summary is not None:
                cur.execute(UPDATE_SUMMARY_SQL, summary_params(app_id, pages.summary))
            cur.execute(MARK_BACKFILLED_SQL, (fetched, max_ts, app_id))
        conn.commit()

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
    postgres: PostgresResource,
) -> MaterializeResult:
    rows = postgres.fetch_all(ABSENT_STEAM_IDS)
    zero_ids: list[int] = []
    # (app_id, total_reviews) : le total recensé sert de garde-fou contre les
    # faux signaux de fin de pagination (cf. iter_review_pages).
    light_apps: list[tuple[int, int | None]] = []
    heavy_apps: list[tuple[int, int | None]] = []
    for row in rows:
        total_reviews = row["total_reviews"]
        size = total_reviews if total_reviews is not None else row["steam_count"]
        if total_reviews == 0:
            zero_ids.append(row["app_id"])
        elif (size or 0) > HEAVY_REVIEW_THRESHOLD:
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
    # Jeux dont la pagination s'est arrêtée trop tôt malgré les relances : ni
    # insérés ni marqués, ils repasseront au prochain run.
    incomplete = 0
    start = time.monotonic()

    if zero_ids:
        with postgres.connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    MARK_BACKFILLED_SQL, [(0, 0, app_id) for app_id in zero_ids]
                )
            conn.commit()
        backfilled += len(zero_ids)
        context.log.info(
            f"[sans review] {len(zero_ids)} jeux marqués backfillés directement, "
            "0 appel API."
        )

    with (
        postgres.connect() as conn,
        ThreadPoolExecutor(max_workers=CENSUS_WORKERS) as pool,
    ):
        for batch_num, batch_start in enumerate(
            range(0, len(light_apps), CENSUS_BATCH_SIZE), start=1
        ):
            batch = light_apps[batch_start : batch_start + CENSUS_BATCH_SIZE]
            reviews_by_app = pool.map(
                lambda app: fetch_steam_reviews(steam, app[0], app[1]),
                batch,
            )
            batch_rows = []
            mark_params = []
            summaries = []
            for (app_id, _), (app_reviews, pages) in zip(batch, reviews_by_app):
                if pages.summary is not None:
                    summaries.append(summary_params(app_id, pages.summary))
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
                mark_params.append((len(app_reviews), app_max_ts, app_id))
            with conn.cursor() as cur:
                if summaries:
                    cur.executemany(UPDATE_SUMMARY_SQL, summaries)
                if batch_rows:
                    cur.executemany(INSERT_REVIEWS_SQL, batch_rows)
                if mark_params:
                    cur.executemany(MARK_BACKFILLED_SQL, mark_params)
            conn.commit()
            loaded += len(batch_rows)
            backfilled += len(mark_params)
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
                backfill_heavy_app_id, steam, postgres, context, app_id, total_reviews
            ): app_id
            for app_id, total_reviews in heavy_apps
        }
        for future in as_completed(futures):
            app_id = futures[future]
            try:
                app_loaded, complete = future.result()
            except Exception:
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
            "tôt malgré les relances) : rien n'a été inséré pour eux, ils seront "
            "repris au prochain run."
        )

    return MaterializeResult(
        metadata={
            "reviews_loaded": MetadataValue.int(loaded),
            "apps_backfilled": MetadataValue.int(backfilled),
            "apps_incomplete": MetadataValue.int(incomplete),
        }
    )
