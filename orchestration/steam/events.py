import json
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, NamedTuple

from dagster import (
    AssetExecutionContext,
    Config,
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

# has_events distingue les jeux déjà ingérés, qui n'ont plus besoin que de leur
# page récente, de ceux dont l'historique reste à charger.
SELECT_APPS_SQL = """
SELECT
    c.app_id,
    EXISTS (
        SELECT 1 FROM raw.steam_events AS e WHERE e.app_id = c.app_id
    ) AS has_events
FROM raw.steam_review_counts AS c
WHERE c.total_reviews >= %s
ORDER BY c.total_reviews DESC;
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


class SteamEventsConfig(Config):
    """Exposé dans le Launchpad : rescanne l'historique complet de tous les jeux."""

    full_refresh: bool = False


class AppEvents(NamedTuple):
    """Annonces d'un jeu, ou la raison de leur absence."""

    app_id: int
    events: list[dict[str, Any]]
    missing_hub: bool = False
    failed: bool = False


@asset(
    group_name="ingest",
    deps=["steam_review_counts"],
    description=(
        "Annonces Steam (patch notes, MAJ, actus) des jeux au-dessus du seuil. "
        "Page récente seule pour les jeux déjà ingérés, sauf full_refresh."
    ),
)
def steam_events(
    context: AssetExecutionContext,
    config: SteamEventsConfig,
    steam: SteamResource,
    postgres: PostgresResource,
) -> MaterializeResult:
    apps = [
        (row["app_id"], config.full_refresh or not row["has_events"])
        for row in postgres.fetch_all(SELECT_APPS_SQL, (MIN_TOTAL_REVIEWS,))
    ]
    total = len(apps)
    full_history = sum(1 for _, whole in apps if whole)
    context.log.info(
        f"Annonces de {total} jeux (>= {MIN_TOTAL_REVIEWS} reviews, "
        f"{full_history} en historique complet, {EVENTS_WORKERS} workers, "
        f"lots de {EVENTS_BATCH_SIZE})"
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
            batch = apps[batch_start : batch_start + EVENTS_BATCH_SIZE]
            results = list(pool.map(lambda app: fetch_app_events(steam, *app), batch))

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
        context.log.warning(f"{apps_failed} jeux en échec, repris au prochain run")

    return MaterializeResult(
        metadata={
            "apps_scanned": MetadataValue.int(scanned),
            "apps_full_history": MetadataValue.int(full_history),
            "events_upserted": MetadataValue.int(events_upserted),
            "apps_without_hub": MetadataValue.int(apps_without_hub),
            "apps_failed": MetadataValue.int(apps_failed),
            "full_refresh": MetadataValue.bool(config.full_refresh),
        }
    )


def iter_app_events(
    steam: SteamResource, app_id: int, whole_history: bool
) -> Iterator[dict[str, Any]]:
    """Pagine les annonces d'un jeu, ou n'en prend que la page la plus récente."""
    offset = 0
    while True:
        page = steam.get_events(app_id, count=EVENTS_PAGE_SIZE, offset=offset)
        events = page.get("events") or []
        if not events:
            return
        yield from events
        # Steam trie par rtime32_start_time décroissant : la première page suffit
        # à rattraper un jeu déjà ingéré, aucun n'annonce 100 fois par jour.
        if not whole_history:
            return
        offset += len(events)


def fetch_app_events(
    steam: SteamResource, app_id: int, whole_history: bool
) -> AppEvents:
    """Récupère les annonces d'un jeu sans jamais faire tomber le run."""
    logger = get_dagster_logger()
    try:
        return AppEvents(app_id, list(iter_app_events(steam, app_id, whole_history)))
    except SteamApiError as exc:
        if exc.success == NO_ANNOUNCEMENT_HUB:
            return AppEvents(app_id, [], missing_hub=True)
        logger.warning(f"app_id={app_id}: annonces refusées par Steam ({exc})")
        return AppEvents(app_id, [], failed=True)
    except Exception:
        logger.exception(f"app_id={app_id}: échec de la récupération des annonces")
        return AppEvents(app_id, [], failed=True)


def event_to_row(app_id: int, event: dict[str, Any]) -> tuple:
    """Ligne à upserter pour une annonce."""
    # Steam laisse gid à 0 sur certaines annonces : le gid du post prend le relais,
    # sinon elles s'écrasent entre elles sur la PK (app_id, gid).
    gid = str(event["gid"])
    if gid == "0":
        gid = str(event.get("announcement_body", {}).get("gid") or gid)

    return (
        gid,
        app_id,
        json.dumps(event),
        event.get("rtime32_start_time"),
    )
