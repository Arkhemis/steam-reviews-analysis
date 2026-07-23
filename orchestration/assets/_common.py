import json
from typing import Any

import psycopg

INSERT_REVIEWS_SQL = """
INSERT INTO raw.steam_reviews (
    recommendation_id, app_id, payload, timestamp_created, timestamp_updated, loaded_at
)
VALUES (%s, %s, %s, %s, %s, now());
"""


def insert_reviews_page(
    conn: psycopg.Connection,
    app_id: int,
    reviews: list[dict[str, Any]],
) -> tuple[int, int]:
    """Insère une page de reviews en append-only.

    Retourne (nombre inséré, max(timestamp_updated) de la page).
    """
    rows = []
    max_ts_updated = 0
    for r in reviews:
        rec_id = r.get("recommendationid")
        if rec_id is None:
            continue
        ts_created = r.get("timestamp_created")
        ts_updated = r.get("timestamp_updated") or ts_created or 0
        max_ts_updated = max(max_ts_updated, ts_updated)
        rows.append(
            (
                int(rec_id),
                app_id,
                json.dumps(r),
                ts_created,
                ts_updated,
            )
        )

    if rows:
        with conn.cursor() as cur:
            cur.executemany(INSERT_REVIEWS_SQL, rows)

    return len(rows), max_ts_updated


def progress_stats(
    done: int, total: int, elapsed_seconds: float
) -> tuple[float, float, float]:
    """Calcule (pct, jeux/s, ETA en minutes) pour les logs de progression.
    """
    pct = done / total if total else 1.0
    rate = done / elapsed_seconds if elapsed_seconds > 0 else 0.0
    eta_minutes = (total - done) / rate / 60 if rate > 0 else float("inf")
    return pct, rate, eta_minutes
