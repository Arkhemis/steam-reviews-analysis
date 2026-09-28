import hashlib
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

from orchestration.clickhouse import ClickHouseResource
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
    app_id,
    app_id IN (SELECT DISTINCT app_id FROM steam_events) AS has_events
FROM steam_review_counts
-- Un jeu tout juste recensé n'a pas encore de total : son compteur GetItems le remplace.
WHERE coalesce(total_reviews, steam_count) >= {min_total_reviews:Int64}
ORDER BY coalesce(total_reviews, steam_count) DESC
"""


KNOWN_EVENT_SQL = """
SELECT 1
FROM steam_events
WHERE app_id = {app_id:UInt32} AND gid IN {gids:Array(String)}
LIMIT 1
"""

# Empreinte des annonces déjà en base, pour n'écrire que les nouvelles ou modifiées.
KNOWN_HASHES_SQL = """
SELECT app_id, gid, payload_hash
FROM steam_events
WHERE (app_id, gid) IN {keys:Array(Tuple(UInt32, String))}
"""

EVENT_COLUMNS = ["gid", "app_id", "payload", "payload_hash", "rtime32_start_time"]


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
    clickhouse: ClickHouseResource,
) -> MaterializeResult:
    apps = [
        (row["app_id"], config.full_refresh or not row["has_events"])
        for row in clickhouse.query(
            SELECT_APPS_SQL, {"min_total_reviews": MIN_TOTAL_REVIEWS}
        )
    ]
    total = len(apps)
    full_history = sum(1 for _, whole in apps if whole)
    context.log.info(
        f"Annonces de {total} jeux (>= {MIN_TOTAL_REVIEWS} reviews, "
        f"{full_history} en historique complet, {EVENTS_WORKERS} workers, "
        f"lots de {EVENTS_BATCH_SIZE})"
    )

    scanned = 0
    events_fetched = 0
    events_written = 0
    apps_without_hub = 0
    apps_failed = 0
    start = time.monotonic()

    with ThreadPoolExecutor(max_workers=EVENTS_WORKERS) as pool:
        for batch_start in range(0, total, EVENTS_BATCH_SIZE):
            batch = apps[batch_start : batch_start + EVENTS_BATCH_SIZE]
            results = list(
                pool.map(lambda app: fetch_app_events(steam, clickhouse, *app), batch)
            )

            batch_rows = [
                event_to_row(result.app_id, event)
                for result in results
                for event in result.events
            ]
            events_written += write_events(clickhouse, batch_rows)

            scanned += len(batch)
            events_fetched += len(batch_rows)
            apps_without_hub += sum(1 for r in results if r.missing_hub)
            apps_failed += sum(1 for r in results if r.failed)

            elapsed = time.monotonic() - start
            rate = scanned / elapsed if elapsed > 0 else 0
            eta_min = (total - scanned) / rate / 60 if rate > 0 else float("inf")
            context.log.info(
                f"Scanné {scanned}/{total} ({scanned / total:.0%}) "
                f"— {rate:.2f} jeux/s — {events_fetched} annonces ({events_written} écrites) — ETA {eta_min:.0f} min"
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
            "events_fetched": MetadataValue.int(events_fetched),
            "events_written": MetadataValue.int(events_written),
            "apps_without_hub": MetadataValue.int(apps_without_hub),
            "apps_failed": MetadataValue.int(apps_failed),
            "full_refresh": MetadataValue.bool(config.full_refresh),
        }
    )


def write_events(clickhouse: ClickHouseResource, rows: list[tuple]) -> int:
    """Insère les annonces nouvelles ou modifiées, et renvoie leur nombre.

    Chaque page récente revient en entier : sans ce filtre, on réécrirait
    chaque nuit des annonces inchangées et loaded_at ne dirait plus rien.
    """
    # Une même clé peut revenir deux fois dans le lot : la dernière gagne.
    latest = {(row[1], row[0]): row for row in rows}
    if not latest:
        return 0
    known = {
        (row["app_id"], row["gid"]): row["payload_hash"]
        for row in clickhouse.query(KNOWN_HASHES_SQL, {"keys": list(latest)})
    }
    changed = [row for key, row in latest.items() if known.get(key) != row[3]]
    clickhouse.insert("steam_events", changed, EVENT_COLUMNS)
    return len(changed)


def has_known_event(
    clickhouse: ClickHouseResource, app_id: int, events: list[dict[str, Any]]
) -> bool:
    """Dit si l'une des annonces de la page est déjà en base."""
    gids = [event_gid(event) for event in events]
    return bool(clickhouse.query(KNOWN_EVENT_SQL, {"app_id": app_id, "gids": gids}))


def iter_app_events(
    steam: SteamResource,
    clickhouse: ClickHouseResource,
    app_id: int,
    whole_history: bool,
) -> Iterator[dict[str, Any]]:
    """Pagine les annonces d'un jeu jusqu'à retomber sur une annonce déjà connue."""
    offset = 0
    while True:
        page = steam.get_events(app_id, count=EVENTS_PAGE_SIZE, offset=offset)
        events = page.get("events") or []
        if not events:
            return
        yield from events
        # Steam trie par rtime32_start_time décroissant : un gid déjà en base
        # signifie que le retard est rattrapé, quel qu'il soit.
        if not whole_history and has_known_event(clickhouse, app_id, events):
            return
        offset += len(events)


def fetch_app_events(
    steam: SteamResource,
    clickhouse: ClickHouseResource,
    app_id: int,
    whole_history: bool,
) -> AppEvents:
    """Récupère les annonces d'un jeu sans jamais faire tomber le run."""
    logger = get_dagster_logger()
    try:
        return AppEvents(
            app_id, list(iter_app_events(steam, clickhouse, app_id, whole_history))
        )
    except SteamApiError as exc:
        if exc.success == NO_ANNOUNCEMENT_HUB:
            return AppEvents(app_id, [], missing_hub=True)
        logger.warning(f"app_id={app_id}: annonces refusées par Steam ({exc})")
        return AppEvents(app_id, [], failed=True)
    except Exception:
        logger.exception(f"app_id={app_id}: échec de la récupération des annonces")
        return AppEvents(app_id, [], failed=True)


def event_gid(event: dict[str, Any]) -> str:
    """Clé de l'annonce : le gid du post relaie celui de l'événement quand Steam
    le laisse à 0, sinon elles s'écrasent entre elles sur la clé (app_id, gid)."""
    gid = str(event["gid"])
    if gid == "0":
        return str(event.get("announcement_body", {}).get("gid") or gid)
    return gid


def event_to_row(app_id: int, event: dict[str, Any]) -> tuple:
    """Ligne à insérer pour une annonce, empreinte du payload comprise."""
    payload = json.dumps(event)
    return (
        event_gid(event),
        app_id,
        payload,
        payload_hash(payload),
        event.get("rtime32_start_time"),
    )


def payload_hash(payload: str) -> int:
    """Empreinte stable sur 64 bits (hash() de Python change à chaque processus)."""
    digest = hashlib.blake2b(payload.encode(), digest_size=8).digest()
    return int.from_bytes(digest, "little")
