import json
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, NamedTuple

from dagster import (
    AssetExecutionContext,
    MaterializeResult,
    MetadataValue,
    asset,
    get_dagster_logger,
)

from orchestration.postgres import PostgresResource
from orchestration.steam.resources import SteamApiError, SteamResource

EVENTS_WORKERS = 8
EVENTS_BATCH_SIZE = 100
EVENTS_PAGE_SIZE = 100


MIN_TOTAL_REVIEWS = 100

# `success = 42` : Steam n'a pas su résoudre le groupe officiel de cet appid.
NO_ANNOUNCEMENT_HUB = 42

SELECT_APP_IDS_SQL = """
SELECT app_id
FROM raw.steam_review_counts
WHERE total_reviews >= %s
ORDER BY total_reviews DESC;
"""


UPSERT_EVENT_SQL = """
INSERT INTO raw.steam_events (
    gid, app_id, payload, rtime32_start_time
)
VALUES (%s, %s, %s, %s)
ON CONFLICT (app_id, gid) DO UPDATE
SET payload            = EXCLUDED.payload,
    rtime32_start_time = EXCLUDED.rtime32_start_time,
    loaded_at          = now()
"""


class AppEvents(NamedTuple):
    """Annonces d'un jeu, ou la raison de leur absence."""

    app_id: int
    events: list[dict[str, Any]]
    missing_hub: bool = False
    failed: bool = False


@asset(
    group_name="ingest",
    deps=["steam_review_counts"],
    description="Annonces Steam (patch notes, MAJ, actus) des jeux au-dessus du seuil",
)
def steam_events(
    context: AssetExecutionContext,
    steam: SteamResource,
    postgres: PostgresResource,
) -> MaterializeResult:
    rows = postgres.fetch_all(SELECT_APP_IDS_SQL, (MIN_TOTAL_REVIEWS,))
    app_ids = [row["app_id"] for row in rows]
    total = len(app_ids)
    context.log.info(
        f"Annonces de {total} jeux (>= {MIN_TOTAL_REVIEWS} reviews, "
        f"{EVENTS_WORKERS} workers, lots de {EVENTS_BATCH_SIZE})"
    )

    scanned = 0
    events_upserted = 0
    apps_without_hub = 0
    apps_failed = 0
    start = time.monotonic()

    with (
        postgres.connect() as conn,
        ThreadPoolExecutor(max_workers=EVENTS_WORKERS) as pool,
    ):
        for batch_start in range(0, total, EVENTS_BATCH_SIZE):
            batch = app_ids[batch_start : batch_start + EVENTS_BATCH_SIZE]
            results = list(
                pool.map(lambda app_id: fetch_app_events(steam, app_id), batch)
            )

            batch_rows = [
                event_to_row(result.app_id, event)
                for result in results
                for event in result.events
            ]
            if batch_rows:
                with conn.cursor() as cur:
                    cur.executemany(UPSERT_EVENT_SQL, batch_rows)
            conn.commit()

            scanned += len(batch)
            events_upserted += len(batch_rows)
            apps_without_hub += sum(1 for r in results if r.missing_hub)
            apps_failed += sum(1 for r in results if r.failed)

            elapsed = time.monotonic() - start
            rate = scanned / elapsed if elapsed > 0 else 0
            eta_min = (total - scanned) / rate / 60 if rate > 0 else float("inf")
            context.log.info(
                f"Scanné {scanned}/{total} ({scanned / total:.0%}) "
                f"— {rate:.2f} jeux/s — {events_upserted} annonces — ETA {eta_min:.0f} min"
            )

    if apps_without_hub:
        context.log.info(
            f"{apps_without_hub} jeux sans hub d'annonces (success={NO_ANNOUNCEMENT_HUB}) : "
        )
    if apps_failed:
        context.log.warning(
            f"{apps_failed} jeux en échec, repris au prochain run"
        )

    return MaterializeResult(
        metadata={
            "apps_scanned": MetadataValue.int(scanned),
            "events_upserted": MetadataValue.int(events_upserted),
            "apps_without_hub": MetadataValue.int(apps_without_hub),
            "apps_failed": MetadataValue.int(apps_failed),
        }
    )


def iter_app_events(steam: SteamResource, app_id: int) -> Iterator[dict[str, Any]]:
    """Pagine les annonces d'un jeu.
    """
    offset = 0
    while True:
        page = steam.get_events(app_id, count=EVENTS_PAGE_SIZE, offset=offset)
        events = page.get("events") or []
        if not events:
            return
        yield from events
        offset += len(events)


def fetch_app_events(steam: SteamResource, app_id: int) -> AppEvents:
    """Récupère toutes les annonces d'un jeu sans jamais faire tomber le run."""
    logger = get_dagster_logger()
    try:
        return AppEvents(app_id, list(iter_app_events(steam, app_id)))
    except SteamApiError as exc:
        if exc.success == NO_ANNOUNCEMENT_HUB:
            return AppEvents(app_id, [], missing_hub=True)
        logger.warning(f"app_id={app_id}: annonces refusées par Steam ({exc})")
        return AppEvents(app_id, [], failed=True)
    except Exception:
        logger.exception(f"app_id={app_id}: échec de la récupération des annonces")
        return AppEvents(app_id, [], failed=True)


def event_to_row(app_id: int, event: dict[str, Any]) -> tuple:
    """Ligne à upserter pour une annonce.
    """
    return (
        event["gid"],
        app_id,
        json.dumps(event),
        event.get("rtime32_start_time"),
    )
