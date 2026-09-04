import json
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, NamedTuple

import psycopg
from dagster import (
    AssetExecutionContext,
    MaterializeResult,
    MetadataValue,
    asset,
    get_dagster_logger,
)

from orchestration.postgres import PostgresResource
from orchestration.steam.backfill import (
    STOP_BACKOFF_BASE_SECONDS,
    STOP_MAX_RETRIES,
)
from orchestration.steam.resources import SteamResource

# Un thread et une connexion Postgres par jeu en cours de traitement.
INCREMENTAL_WORKERS = 10

# Reviews gardées en mémoire par jeu avant envoi au serveur (afin d'éviter un OOM)
FLUSH_REVIEWS = 5000
PROGRESS_EVERY = 500


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

UPDATE_CHECKPOINT_SQL = """
UPDATE raw.steam_review_counts
SET last_seen_timestamp_updated = GREATEST(
        COALESCE(last_seen_timestamp_updated, 0),
        %s
    )
WHERE app_id = %s
"""

# Un scan par run au lieu d'un par jeu, et le compteur redevient exact quoi
# qu'il ait dérivé. LEFT JOIN pour que les jeux backfillés dont plus aucune
# review n'est stockée retombent à 0 au lieu de garder leur ancien compteur.
RECOUNT_BACKFILLED_SQL = """
WITH stored AS (
    SELECT app_id, count(DISTINCT recommendation_id) AS reviews_stored
    FROM raw.steam_reviews
    GROUP BY app_id
)
UPDATE raw.steam_review_counts AS c
SET total_reviews_backfilled = COALESCE(stored.reviews_stored, 0)
FROM raw.steam_review_counts AS census
LEFT JOIN stored ON stored.app_id = census.app_id
WHERE census.app_id = c.app_id
  AND census.last_backfill_at IS NOT NULL
  AND c.total_reviews_backfilled IS DISTINCT FROM COALESCE(stored.reviews_stored, 0)
"""


class AppSync(NamedTuple):
    """Bilan de la synchronisation d'un jeu (des compteurs, jamais de reviews)."""

    reviews_fetched: int
    versions_inserted: int
    reached_checkpoint: bool


@asset(
    group_name="load",
    # Un jeu n'entre dans l'incrémental qu'une fois backfillé : le backfill pose
    # le `last_seen_timestamp_updated` que RELEVANT_APP_IDS exige.
    deps=["steam_review_counts", "steam_reviews_backfill"],
    description="Incremental backfill des reviews Steam (payload complet) -> raw.steam_reviews.",
)
def steam_reviews_incremental(
    context: AssetExecutionContext,
    steam: SteamResource,
    postgres: PostgresResource,
) -> MaterializeResult:
    relevant_apps = postgres.fetch_all(RELEVANT_APP_IDS)
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
        # Chaque tâche écrit elle-même en base et ne renvoie que des compteurs :
        # les `Future` restent vivantes jusqu'à la fin du run, elles ne doivent
        # donc rien retenir de volumineux.
        futures = {
            pool.submit(
                sync_app_reviews,
                steam,
                postgres,
                row["app_id"],
                row["last_seen_timestamp_updated"],
            ): row["app_id"]
            for row in relevant_apps
        }
        for future in as_completed(futures):
            app_id = futures[future]
            processed += 1
            try:
                result = future.result()
            except Exception:
                # Chaque jeu a sa propre transaction : un échec isolé ne coûte
                # que ce jeu, repris au prochain run.
                apps_failed += 1
                context.log.exception(
                    f"app_id={app_id}: échec de la synchronisation, "
                    "aucune donnée enregistrée (repris au prochain run)"
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

    apps_recounted = recount_backfilled(postgres)
    context.log.info(
        f"total_reviews_backfilled recalculé depuis raw.steam_reviews "
        f"({apps_recounted} jeux corrigés)"
    )

    if apps_incomplete:
        context.log.warning(
            f"{apps_incomplete} jeux laissés incomplets (checkpoint non rejoint) : "
            "rien n'a été enregistré pour eux, ils seront repris au prochain run."
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
    """Pages de reviews d'un jeu postérieures à son checkpoint.

    Les pages sont servies une par une : un jeu dont le checkpoint est ancien
    peut demander des milliers de pages, qui ne doivent jamais coexister en
    mémoire. `filter=updated` garantit un ordre décroissant sur
    `timestamp_updated`, la pagination s'arrête donc dès la première review
    antérieure au checkpoint. Un signal de fin reçu avant le checkpoint est
    traité comme un incident transitoire : le même curseur est rejoué, comme
    dans le backfill.
    """

    def __init__(
        self,
        steam: SteamResource,
        app_id: int,
        last_seen_timestamp_updated: int,
    ) -> None:
        self.steam = steam
        self.app_id = app_id
        self.last_seen_timestamp_updated = last_seen_timestamp_updated
        self.has_checkpoint = last_seen_timestamp_updated > 0
        self.reached_checkpoint = False

    def __iter__(self) -> Iterator[list[dict[str, Any]]]:
        logger = get_dagster_logger()
        cursor = "*"
        stop_retries = 0

        while True:
            review_page = self.steam.get_all_reviews(
                self.app_id, cursor=cursor, language="all"
            )
            reviews = review_page.get("reviews") or []
            next_cursor = review_page.get("cursor")

            page: list[dict[str, Any]] = []
            passed_checkpoint = False
            for review in reviews:
                # On inclut les égalités afin de ne pas perdre une review publiée
                # dans la même seconde que le checkpoint. Elles seront dédupliquées
                # par (recommendation_id, timestamp_updated) avant insertion.
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

            stalled = not reviews or not next_cursor or next_cursor == cursor
            give_up = stalled and stop_retries >= STOP_MAX_RETRIES

            if page and (self.reached_checkpoint or not stalled or give_up):
                yield page
            if passed_checkpoint:
                return

            if stalled:
                if self.reached_checkpoint:
                    return
                # Steam annonce régulièrement une fin de pagination qui n'en est
                # pas une : tant que le checkpoint n'est pas rejoint, on rejoue le
                # même curseur plutôt que d'abandonner le jeu (cf. backfill).
                if give_up:
                    if not self.has_checkpoint:
                        # Rien à rejoindre : après les relances, la fin annoncée
                        # par Steam est le seul signal de fin exploitable.
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
    postgres: PostgresResource,
    app_id: int,
    last_seen_timestamp_updated: int,
) -> AppSync:
    """Pagine un jeu depuis son checkpoint et insère les nouvelles versions au fil de l'eau."""
    logger = get_dagster_logger()
    pages = NewReviewPages(steam, app_id, last_seen_timestamp_updated)
    fetched = 0
    versions_inserted = 0
    max_timestamp_updated = last_seen_timestamp_updated

    with postgres.connect() as conn:
        for batch in iter_review_batches(pages, FLUSH_REVIEWS):
            fetched += len(batch)
            max_timestamp_updated = max(
                max_timestamp_updated,
                max(review["timestamp_updated"] for review in batch),
            )
            versions_inserted += insert_versions(conn, app_id, batch)

        if not pages.reached_checkpoint:
            conn.rollback()
            logger.warning(
                f"app_id={app_id}: checkpoint non atteint ; aucune donnée enregistrée"
            )
            return AppSync(fetched, 0, False)

        with conn.cursor() as cur:
            cur.execute(UPDATE_CHECKPOINT_SQL, (max_timestamp_updated, app_id))
        conn.commit()

    return AppSync(fetched, versions_inserted, True)


def insert_versions(
    conn: psycopg.Connection, app_id: int, reviews: list[dict[str, Any]]
) -> int:
    """Insère les versions du lot sans vérifier ce qui est déjà en base.

    `last_seen_timestamp_updated` est le max des `timestamp_updated` stockés
    pour ce jeu : une review plus récente que le checkpoint ne peut pas y être.
    Seule la seconde-frontière peut donc produire un doublon, que le modèle
    staging écarte déjà (ROW_NUMBER par recommendation_id).
    """
    if not reviews:
        return 0

    # Steam resert parfois une review d'une page à l'autre.
    versions = {
        (int(review["recommendationid"]), review["timestamp_updated"]): review
        for review in reviews
    }
    rows = [review_to_row(app_id, review) for review in versions.values()]
    with conn.cursor() as cur:
        cur.executemany(INSERT_REVIEW_SQL, rows)
    return len(rows)


def recount_backfilled(postgres: PostgresResource) -> int:
    """Réaligne total_reviews_backfilled sur ce que contient raw.steam_reviews."""
    with postgres.connect() as conn:
        with conn.cursor() as cur:
            cur.execute(RECOUNT_BACKFILLED_SQL)
            return cur.rowcount


def review_to_row(app_id: int, review: dict[str, Any]) -> tuple:
    return (
        int(review["recommendationid"]),
        app_id,
        json.dumps(review),
        review["timestamp_created"],
        review["timestamp_updated"],
    )
