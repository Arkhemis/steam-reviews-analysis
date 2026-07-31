import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from orchestration.resources import PostgresResource, SteamResource

# Au-delà de ce volume, un jeu est traité un par un avec pagination streamée
# plutôt que dans un lot classique : sans ça, le stream plante
HEAVY_REVIEW_THRESHOLD = 25000

# Pour les jeux volumineux, on upsert/commit tous les N pages Steam
HEAVY_PAGE_FLUSH_INTERVAL = 1000

ABSENT_STEAM_IDS = """
SELECT app_id, total_reviews FROM raw.steam_review_counts
WHERE last_backfill_at IS NULL OR last_backfill_at < NOW() - INTERVAL '1 month'
ORDER BY total_reviews ASC NULLS FIRST
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
) -> int:
    """Pagine et upsert un jeu volumineux page par page, en flushant tous les
    HEAVY_PAGE_FLUSH_INTERVAL pages pour ne jamais garder tout le jeu en mémoire."""
    loaded = 0
    pending_rows: list[tuple] = []
    pages_since_flush = 0
    cursor = "*"
    with postgres.connect() as conn:
        while True:
            review_page = steam.get_all_reviews(app_id, cursor=cursor, language="all")
            if not review_page.get("reviews") or review_page["cursor"] == cursor:
                break
            pending_rows.extend(reviews_to_rows(app_id, review_page["reviews"]))
            cursor = review_page["cursor"]
            pages_since_flush += 1
            if pages_since_flush >= HEAVY_PAGE_FLUSH_INTERVAL:
                with conn.cursor() as cur:
                    cur.executemany(UPSERT_REVIEWS_SQL, pending_rows)
                conn.commit()
                loaded += len(pending_rows)
                pending_rows = []
                pages_since_flush = 0

        if pending_rows:
            with conn.cursor() as cur:
                cur.executemany(UPSERT_REVIEWS_SQL, pending_rows)
            conn.commit()
            loaded += len(pending_rows)

        with conn.cursor() as cur:
            cur.execute(MARK_BACKFILLED_SQL, (app_id,))
        conn.commit()

    context.log.info(f"[volumineux] app_id={app_id}: {loaded} reviews chargées")
    return loaded


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
    light_ids = [
        row["app_id"]
        for row in rows
        if (row["total_reviews"] or 0) <= HEAVY_REVIEW_THRESHOLD
    ]
    heavy_ids = [
        row["app_id"]
        for row in rows
        if (row["total_reviews"] or 0) > HEAVY_REVIEW_THRESHOLD
    ]
    total = len(light_ids) + len(heavy_ids)
    context.log.info(
        f"Backfill de {total} jeux Steam : {len(light_ids)} légers "
        f"(lots de {CENSUS_BATCH_SIZE}, {CENSUS_WORKERS} workers) et "
        f"{len(heavy_ids)} volumineux (> {HEAVY_REVIEW_THRESHOLD} reviews, "
        f"traités un par un avec pagination streamée)"
    )

    loaded = 0
    backfilled = 0
    start = time.monotonic()

    with (
        postgres.connect() as conn,
        ThreadPoolExecutor(max_workers=CENSUS_WORKERS) as pool,
    ):
        for batch_num, batch_start in enumerate(
            range(0, len(light_ids), CENSUS_BATCH_SIZE), start=1
        ):
            batch = light_ids[batch_start : batch_start + CENSUS_BATCH_SIZE]
            reviews_by_app = pool.map(
                lambda app_id: fetch_steam_reviews(steam, app_id),
                batch,
            )
            batch_rows = []
            for app_id, app_reviews in zip(batch, reviews_by_app):
                batch_rows.extend(reviews_to_rows(app_id, app_reviews))
            with conn.cursor() as cur:
                if batch_rows:
                    cur.executemany(UPSERT_REVIEWS_SQL, batch_rows)
                cur.executemany(MARK_BACKFILLED_SQL, [(app_id,) for app_id in batch])
            conn.commit()
            loaded += len(batch_rows)
            backfilled += len(batch)
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
            pool.submit(backfill_heavy_app_id, steam, postgres, context, app_id): app_id
            for app_id in heavy_ids
        }
        for future in as_completed(futures):
            app_id = futures[future]
            try:
                loaded += future.result()
            except Exception:
                context.log.error(
                    f"[volumineux] app_id={app_id}: échec, sera retenté au "
                    "prochain run (last_backfill_at non mis à jour)"
                )
                continue
            backfilled += 1
            elapsed = time.monotonic() - start
            rate = backfilled / elapsed if elapsed > 0 else 0
            eta_min = (total - backfilled) / rate / 60 if rate > 0 else float("inf")
            context.log.info(
                f"[volumineux] Backfillé {backfilled}/{total} ({backfilled / total:.0%}) "
                f"— {loaded} reviews chargées — ETA {eta_min:.0f} min"
            )

    return MaterializeResult(metadata={"reviews_loaded": MetadataValue.int(loaded)})
