import itertools
import json
import time

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from orchestration.clickhouse import ClickHouseResource
from orchestration.steam.resources import SteamResource

GAME_DETAILS_BATCH_SIZE = 200

SELECT_APPS_SQL = """
SELECT DISTINCT app_id
FROM steam_review_counts
ORDER BY app_id
"""


@asset(
    group_name="ingest",
    deps=["steam_review_counts"],
    description=(
        "Fiches store Steam (type d'app, jeu parent des DLC, early access, dates "
        "de sortie) de tous les jeux recensés -> raw.steam_game_details."
    ),
)
def steam_game_details(
    context: AssetExecutionContext,
    steam: SteamResource,
    clickhouse: ClickHouseResource,
) -> MaterializeResult:
    app_ids = [row["app_id"] for row in clickhouse.query(SELECT_APPS_SQL)]
    total = len(app_ids)
    context.log.info(
        f"Fiches store de {total} jeux (lots de {GAME_DETAILS_BATCH_SIZE})"
    )

    scanned = 0
    upserted = 0
    unavailable = 0
    batches_failed = 0
    start = time.monotonic()

    for batch in itertools.batched(app_ids, GAME_DETAILS_BATCH_SIZE):
        scanned += len(batch)
        try:
            items = steam.get_store_items(list(batch))
        except Exception:
            context.log.exception(f"Lot à partir de app_id={batch[0]} en échec")
            batches_failed += 1
            continue

        rows = [(item["id"], json.dumps(item)) for item in items]
        clickhouse.insert("steam_game_details", rows, ["app_id", "payload"])

        upserted += len(rows)
        unavailable += sum(1 for item in items if item.get("success") != 1)

        elapsed = time.monotonic() - start
        context.log.info(
            f"Scanné {scanned}/{total} ({scanned / total:.0%}) "
            f"— {scanned / elapsed:.0f} jeux/s — {unavailable} indisponibles"
        )

    if batches_failed:
        context.log.warning(f"{batches_failed} lots en échec, repris au prochain run")

    return MaterializeResult(
        metadata={
            "apps_scanned": MetadataValue.int(scanned),
            "rows_upserted": MetadataValue.int(upserted),
            "apps_unavailable": MetadataValue.int(unavailable),
            "batches_failed": MetadataValue.int(batches_failed),
        }
    )
