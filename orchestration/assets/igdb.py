import csv
import json
import sys
import tempfile
from pathlib import Path

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from orchestration.resources import IGDBResource, PostgresResource

BATCH_SIZE = 1000

UPSERT_SQL = """
INSERT INTO raw.igdb_games (igdb_id, steam_app_id, name, payload, loaded_at)
VALUES (%s, %s, %s, %s, now())
ON CONFLICT (igdb_id) DO UPDATE
SET steam_app_id = EXCLUDED.steam_app_id,
    name         = EXCLUDED.name,
    payload      = EXCLUDED.payload,
    loaded_at    = now();
"""

# Relève la limite de taille de champ CSV pour ne pas planter.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def _steam_app_ids_from_external_dump(path: Path) -> dict[int, int]:
    """Parcourt le dump `external_games` → { igdb_id: steam_app_id }."""
    STEAM_CATEGORY = 1  # enum ExternalGameCategory : steam = 1 
    mapping: dict[int, int] = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            category = (row.get("category") or row.get("external_game_source") or "").strip()
            if not category.isdigit() or int(category) != STEAM_CATEGORY:
                continue
            game_id = row.get("game")
            uid = (row.get("uid") or "").strip()
            if game_id is not None and uid.isdigit():
                mapping[game_id] = int(uid)
    return mapping


@asset(
    group_name="ingest",
    description=(
        "Liste des jeux IGDB et leur steam_app_id, via les data dumps IGDB "
        "(external_games + games). Upsert dans raw.igdb_games."
    ),
)
def igdb_games(
    context: AssetExecutionContext,
    igdb: IGDBResource,
    postgres: PostgresResource,
) -> MaterializeResult:
    with tempfile.TemporaryDirectory(prefix="igdb_dumps_") as tmp:
        tmp_dir = Path(tmp)

        # 1) external_games -> map igdb_id -> steam_app_id
        external_path = igdb.download_dump("external_games", tmp_dir)
        steam_by_game = _steam_app_ids_from_external_dump(external_path)
        context.log.info(f"IGDB : {len(steam_by_game)} jeux avec un app_id Steam")

        # 2) games -> nom + upsert (uniquement les jeux liés à Steam)
        games_path = igdb.download_dump("games", tmp_dir)

        total_games = 0
        upserted = 0
        with (
            open(games_path, newline="", encoding="utf-8", errors="replace") as f,
            postgres.connect() as conn,
        ):
            reader = csv.DictReader(f)
            batch: list[tuple] = []
            for row in reader:
                total_games += 1
                igdb_id = row.get("id")
                steam_app_id = steam_by_game.get(igdb_id)
                if igdb_id is None or steam_app_id is None:
                    continue

                payload = {
                    "id": igdb_id,
                    "name": row.get("name"),
                    "slug": row.get("slug"),
                    "steam_app_id": steam_app_id,
                }
                batch.append(
                    (igdb_id, steam_app_id, row.get("name"), json.dumps(payload))
                )

                if len(batch) >= BATCH_SIZE:
                    _flush(conn, batch)
                    upserted += len(batch)
                    batch = []
                    context.log.info(f"IGDB : {upserted} jeux Steam upsertés")

            if batch:
                _flush(conn, batch)
                upserted += len(batch)

    return MaterializeResult(
        metadata={
            "games_in_dump": MetadataValue.int(total_games),
            "games_with_steam_app_id": MetadataValue.int(len(steam_by_game)),
            "rows_upserted": MetadataValue.int(upserted),
        }
    )


def _flush(conn, batch: list[tuple]) -> None:
    with conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, batch)
