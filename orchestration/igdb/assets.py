import csv
import sys
import tempfile
from datetime import date
from pathlib import Path

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from orchestration.igdb.resources import IGDBResource
from orchestration.clickhouse import ClickHouseResource

BATCH_SIZE = 1000

COVER_URL_TEMPLATE = "https://images.igdb.com/igdb/image/upload/t_720p/{image_id}.jpg"

COLUMNS = [
    "igdb_id",
    "steam_app_id",
    "name",
    "first_release_date",
    "genres",
    "developers",
    "publishers",
    "cover_url",
]

# Certains champs des dumps dépassent la limite CSV par défaut.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def _steam_app_ids_from_external_dump(path: Path) -> dict[str, int]:
    STEAM_CATEGORY = 1  # enum ExternalGameCategory : steam = 1
    mapping: dict[str, int] = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            category = (
                row.get("category") or row.get("external_game_source") or ""
            ).strip()
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
        "(external_games + games), enrichie des genres, developers, publishers, "
        "cover et date de sortie (dumps genres + companies + "
        "involved_companies + covers). Insertion dans raw.igdb_games."
    ),
)
def igdb_games(
    context: AssetExecutionContext,
    igdb: IGDBResource,
    clickhouse: ClickHouseResource,
) -> MaterializeResult:
    with tempfile.TemporaryDirectory(prefix="igdb_dumps_") as tmp:
        tmp_dir = Path(tmp)

        external_path = igdb.download_dump("external_games", tmp_dir)
        steam_by_game = _steam_app_ids_from_external_dump(external_path)
        external_path.unlink()
        context.log.info(f"IGDB : {len(steam_by_game)} jeux avec un app_id Steam")

        genres_path = igdb.download_dump("genres", tmp_dir)
        with open(genres_path, newline="", encoding="utf-8", errors="replace") as f:
            genre_names = {row["id"]: row["name"] for row in csv.DictReader(f)}
        genres_path.unlink()

        companies_path = igdb.download_dump("companies", tmp_dir)
        with open(companies_path, newline="", encoding="utf-8", errors="replace") as f:
            company_names = {row["id"]: row["name"] for row in csv.DictReader(f)}
        companies_path.unlink()

        involved_path = igdb.download_dump("involved_companies", tmp_dir)
        with open(involved_path, newline="", encoding="utf-8", errors="replace") as f:
            involved_companies = {
                row["id"]: (
                    row["company"],
                    row["developer"] == "t",
                    row["publisher"] == "t",
                )
                for row in csv.DictReader(f)
            }
        involved_path.unlink()

        covers_path = igdb.download_dump("covers", tmp_dir)
        with open(covers_path, newline="", encoding="utf-8", errors="replace") as f:
            cover_image_ids = {
                row["id"]: row["image_id"]
                for row in csv.DictReader(f)
                if row["image_id"]
            }
        covers_path.unlink()

        context.log.info(
            f"IGDB : {len(genre_names)} genres, {len(company_names)} sociétés, "
            f"{len(involved_companies)} liens société↔jeu, "
            f"{len(cover_image_ids)} covers"
        )

        games_path = igdb.download_dump("games", tmp_dir)

        total_games = 0
        upserted = 0
        with open(games_path, newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            batch: list[tuple] = []
            for row in reader:
                total_games += 1
                igdb_id = row.get("id")
                steam_app_id = steam_by_game.get(igdb_id)
                if igdb_id is None or steam_app_id is None:
                    continue

                genre_raw = row.get("genres") or ""
                genres = [
                    genre_names[genre_id]
                    for genre_id in genre_raw.strip("{}").split(",")
                    if genre_id in genre_names
                ]

                developers: list[str] = []
                publishers: list[str] = []
                involved_raw = row.get("involved_companies") or ""
                for involved_id in involved_raw.strip("{}").split(","):
                    involved = involved_companies.get(involved_id)
                    if involved is None:
                        continue
                    company_id, est_dev, est_publisher = involved
                    company_name = company_names.get(company_id)
                    if company_name is None:
                        continue
                    if est_dev:
                        developers.append(company_name)
                    if est_publisher:
                        publishers.append(company_name)

                image_id = cover_image_ids.get(row.get("cover") or "")
                cover_url = (
                    COVER_URL_TEMPLATE.format(image_id=image_id) if image_id else None
                )

                released = row.get("first_release_date")
                first_release_date = (
                    date.fromisoformat(released[:10]) if released else None
                )

                batch.append(
                    (
                        int(igdb_id),
                        steam_app_id,
                        row.get("name"),
                        first_release_date,
                        list(dict.fromkeys(genres)),
                        list(dict.fromkeys(developers)),
                        list(dict.fromkeys(publishers)),
                        cover_url,
                    )
                )

                if len(batch) >= BATCH_SIZE:
                    clickhouse.insert("igdb_games", batch, COLUMNS)
                    upserted += len(batch)
                    batch = []
                    context.log.info(f"IGDB : {upserted} jeux Steam insérés")

            if batch:
                clickhouse.insert("igdb_games", batch, COLUMNS)
                upserted += len(batch)

    return MaterializeResult(
        metadata={
            "games_in_dump": MetadataValue.int(total_games),
            "games_with_steam_app_id": MetadataValue.int(len(steam_by_game)),
            "rows_upserted": MetadataValue.int(upserted),
        }
    )
