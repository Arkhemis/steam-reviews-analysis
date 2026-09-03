import json
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
from orchestration.steam.resources import SteamResource

# Un thread et une connexion Postgres par jeu en cours de traitement.
INCREMENTAL_WORKERS = 10

# Reviews gardées en mémoire par jeu avant envoi au serveur. La mémoire du
# process est ainsi bornée à ~ INCREMENTAL_WORKERS * FLUSH_REVIEWS reviews,
# quels que soient le nombre de jeux et l'ancienneté de leur checkpoint. Le
# seuil est assez haut pour que la grande majorité des jeux (quelques pages de
# retard) tienne en un seul lot, donc une seule requête d'existence.
FLUSH_REVIEWS = 5000

# Périodicité des logs d'avancement (un log par jeu noierait le run).
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


class AppSync(NamedTuple):
    """Bilan de la synchronisation d'un jeu (des compteurs, jamais de reviews)."""

    reviews_fetched: int
    versions_inserted: int
    new_reviews: int
    reached_checkpoint: bool


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
                    f"app_id={app_id}: {result.versions_inserted} versions "
                    f"insérées, dont {result.new_reviews} nouvelles reviews"
                )
            if processed % PROGRESS_EVERY == 0:
                context.log.info(
                    f"Synchronisé {processed}/{total} jeux "
                    f"— {review_versions_inserted} versions insérées"
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
        }
    )


class NewReviewPages:
    """Pages de reviews d'un jeu postérieures à son checkpoint.

    Les pages sont servies une par une : un jeu dont le checkpoint est ancien
    peut demander des milliers de pages, qui ne doivent jamais coexister en
    mémoire. `filter=updated` garantit un ordre décroissant sur
    `timestamp_updated`, la pagination s'arrête donc dès la première review
    antérieure au checkpoint.

    Après itération, `reached_checkpoint` dit si la pagination a effectivement
    rejoint le checkpoint. Sinon Steam a interrompu la pagination avant : il
    manque des reviews entre les dernières servies et le checkpoint, et
    l'appelant doit tout annuler plutôt que de créer un trou définitif.
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
        # Un jeu sans checkpoint n'a rien à rejoindre : tout est nouveau.
        self.reached_checkpoint = last_seen_timestamp_updated == 0

    def __iter__(self) -> Iterator[list[dict[str, Any]]]:
        logger = get_dagster_logger()
        cursor = "*"

        while True:
            review_page = self.steam.get_all_reviews(
                self.app_id, cursor=cursor, language="all"
            )
            reviews = review_page.get("reviews") or []
            next_cursor = review_page.get("cursor")

            if not reviews:
                return

            page: list[dict[str, Any]] = []
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
                    if page:
                        yield page
                    return
                if review["timestamp_updated"] == self.last_seen_timestamp_updated:
                    self.reached_checkpoint = True
                page.append(review)

            yield page

            if not next_cursor or next_cursor == cursor:
                return
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
    """Pagine un jeu depuis son checkpoint et insère les nouvelles versions au fil de l'eau.

    Les lots sont envoyés au serveur puis oubliés : le retard d'un jeu ne
    détermine plus la mémoire du process, seulement le volume écrit. Le commit
    n'a lieu qu'une fois le checkpoint rejoint ; sinon la transaction est
    annulée et le jeu repart de son ancien checkpoint au prochain run.
    """
    logger = get_dagster_logger()
    pages = NewReviewPages(steam, app_id, last_seen_timestamp_updated)
    fetched = 0
    versions_inserted = 0
    new_reviews = 0
    max_timestamp_updated = last_seen_timestamp_updated

    with postgres.connect() as conn:
        for batch in iter_review_batches(pages, FLUSH_REVIEWS):
            fetched += len(batch)
            max_timestamp_updated = max(
                max_timestamp_updated,
                max(review["timestamp_updated"] for review in batch),
            )
            inserted, new = insert_new_versions(conn, app_id, batch)
            versions_inserted += inserted
            new_reviews += new

        if not pages.reached_checkpoint:
            conn.rollback()
            logger.warning(
                f"app_id={app_id}: checkpoint non atteint ; aucune donnée enregistrée"
            )
            return AppSync(fetched, 0, 0, False)

        with conn.cursor() as cur:
            cur.execute(
                UPDATE_REVIEW_COUNT_SQL,
                (new_reviews, max_timestamp_updated, app_id),
            )
        conn.commit()

    return AppSync(fetched, versions_inserted, new_reviews, True)


def insert_new_versions(
    conn: psycopg.Connection, app_id: int, reviews: list[dict[str, Any]]
) -> tuple[int, int]:
    """Insère les versions du lot absentes de la base.

    Renvoie (versions insérées, reviews jamais vues). Les lignes des lots
    précédents, envoyées mais pas encore commitées, sont visibles par la
    requête d'existence : le dédoublonnage tient d'un lot au suivant.
    """
    if not reviews:
        return 0, 0

    # Dédoublonnage intra-lot : Steam resert parfois une review d'une page à
    # l'autre, et une review peut être servie deux fois dans la même seconde.
    versions = {
        (int(review["recommendationid"]), review["timestamp_updated"]): review
        for review in reviews
    }
    recommendation_ids = list({recommendation_id for recommendation_id, _ in versions})

    existing_versions: set[tuple[int, int]] = set()
    existing_recommendation_ids: set[int] = set()
    with conn.cursor() as cur:
        cur.execute(EXISTING_REVIEW_VERSIONS_SQL, (app_id, recommendation_ids))
        for row in cur.fetchall():
            existing_versions.add((row["recommendation_id"], row["timestamp_updated"]))
            existing_recommendation_ids.add(row["recommendation_id"])

    rows = [
        review_to_row(app_id, review)
        for version, review in versions.items()
        if version not in existing_versions
    ]
    if rows:
        with conn.cursor() as cur:
            cur.executemany(INSERT_REVIEW_SQL, rows)

    new_reviews = len(set(recommendation_ids) - existing_recommendation_ids)
    return len(rows), new_reviews


def review_to_row(app_id: int, review: dict[str, Any]) -> tuple:
    return (
        int(review["recommendationid"]),
        app_id,
        json.dumps(review),
        review["timestamp_created"],
        review["timestamp_updated"],
    )
