import csv
import sys
import tempfile
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pycountry
from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from orchestration.clickhouse import ClickHouseResource
from orchestration.igdb.resources import IGDBResource

BATCH_SIZE = 1000

COVER_URL_TEMPLATE = "https://images.igdb.com/igdb/image/upload/t_720p/{image_id}.jpg"

COLUMNS = [
    "igdb_id",
    "steam_app_id",
    "name",
    "alternative_names",
    "first_release_date",
    "game_type",
    "game_status",
    "genres",
    "themes",
    "game_modes",
    "player_perspectives",
    "game_engines",
    "developers",
    "publishers",
    "porting_companies",
    "supporting_companies",
    "developer_countries",
    "parent_companies",
    "cover_url",
]

# Certains champs des dumps dépassent la limite CSV par défaut.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


def _read_dump(path: Path) -> Iterator[dict[str, str]]:
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        yield from csv.DictReader(f)


def _ids(raw: str | None) -> list[str]:
    return [i for i in (raw or "").strip("{}").split(",") if i]


def _labels(raw: str | None, names: dict[str, str]) -> list[str]:
    return list(dict.fromkeys(names[i] for i in _ids(raw) if i in names))


def _labels_by_id(path: Path, column: str = "name") -> dict[str, str]:
    labels = {row["id"]: row[column] for row in _read_dump(path)}
    path.unlink()
    return labels


def _steam_app_ids_from_external_dump(path: Path) -> dict[str, list[int]]:
    STEAM_CATEGORY = 1  # enum ExternalGameCategory : steam = 1
    mapping: dict[str, list[int]] = {}
    for row in _read_dump(path):
        category = (
            row.get("category") or row.get("external_game_source") or ""
        ).strip()
        if not category.isdigit() or int(category) != STEAM_CATEGORY:
            continue
        game_id = row.get("game")
        uid = (row.get("uid") or "").strip()
        if game_id is not None and uid.isdigit():
            mapping.setdefault(game_id, []).append(int(uid))
    return mapping


def _top_parent(company_id: str, parents: dict[str, str]) -> str:
    seen = {company_id}
    while (parent := parents.get(company_id)) and parent not in seen:
        seen.add(parent)
        company_id = parent
    return company_id


def _country_alpha_2(numeric: str) -> str | None:
    country = pycountry.countries.get(numeric=numeric.zfill(3)) if numeric else None
    return country.alpha_2 if country else None


@asset(
    group_name="ingest",
    description=(
        "Liste des jeux IGDB et leur steam_app_id, via les data dumps IGDB "
        "(external_games + games), enrichie des noms alternatifs, du type et "
        "du statut, des genres, thèmes, modes de jeu, perspectives et moteurs, "
        "des sociétés impliquées (rôle, pays, groupe), de la cover et de la "
        "date de sortie. Insertion dans raw.igdb_games."
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

        alternative_names_path = igdb.download_dump("alternative_names", tmp_dir)
        alternative_names: dict[str, list[str]] = {}
        for row in _read_dump(alternative_names_path):
            if (
                row["game"] in steam_by_game
                and row["name"]
                and row["comment"] != "Windows Executable"
            ):
                alternative_names.setdefault(row["game"], []).append(row["name"])
        alternative_names_path.unlink()

        game_types = _labels_by_id(igdb.download_dump("game_types", tmp_dir), "type")
        game_statuses = _labels_by_id(
            igdb.download_dump("game_statuses", tmp_dir), "status"
        )
        genre_names = _labels_by_id(igdb.download_dump("genres", tmp_dir))
        theme_names = _labels_by_id(igdb.download_dump("themes", tmp_dir))
        game_mode_names = _labels_by_id(igdb.download_dump("game_modes", tmp_dir))
        perspective_names = _labels_by_id(
            igdb.download_dump("player_perspectives", tmp_dir)
        )
        engine_names = _labels_by_id(igdb.download_dump("game_engines", tmp_dir))

        companies_path = igdb.download_dump("companies", tmp_dir)
        company_names: dict[str, str] = {}
        company_countries: dict[str, str] = {}
        company_parents: dict[str, str] = {}
        for row in _read_dump(companies_path):
            company_names[row["id"]] = row["name"]
            if country := _country_alpha_2(row["country"]):
                company_countries[row["id"]] = country
            if row["parent"]:
                company_parents[row["id"]] = row["parent"]
        companies_path.unlink()

        involved_path = igdb.download_dump("involved_companies", tmp_dir)
        involved_companies = {
            row["id"]: (
                row["company"],
                row["developer"] == "t",
                row["publisher"] == "t",
                row["porting"] == "t",
                row["supporting"] == "t",
            )
            for row in _read_dump(involved_path)
        }
        involved_path.unlink()

        covers_path = igdb.download_dump("covers", tmp_dir)
        cover_image_ids = {
            row["id"]: row["image_id"]
            for row in _read_dump(covers_path)
            if row["image_id"]
        }
        covers_path.unlink()

        context.log.info(
            f"IGDB : {len(genre_names)} genres, {len(theme_names)} thèmes, "
            f"{len(engine_names)} moteurs, {len(company_names)} sociétés, "
            f"{len(involved_companies)} liens société↔jeu, "
            f"{len(cover_image_ids)} covers"
        )

        games_path = igdb.download_dump("games", tmp_dir)

        total_games = 0
        upserted = 0
        batch: list[tuple] = []
        for row in _read_dump(games_path):
            total_games += 1
            igdb_id = row.get("id")
            steam_app_ids = steam_by_game.get(igdb_id)
            if igdb_id is None or steam_app_ids is None:
                continue

            developers: list[str] = []
            publishers: list[str] = []
            porting_companies: list[str] = []
            supporting_companies: list[str] = []
            developer_countries: list[str] = []
            parent_companies: list[str] = []
            for involved_id in _ids(row.get("involved_companies")):
                involved = involved_companies.get(involved_id)
                if involved is None:
                    continue
                company_id, is_dev, is_publisher, is_porting, is_supporting = involved
                company_name = company_names.get(company_id)
                if company_name is None:
                    continue
                if is_dev:
                    developers.append(company_name)
                    if country := company_countries.get(company_id):
                        developer_countries.append(country)
                if is_publisher:
                    publishers.append(company_name)
                if is_porting:
                    porting_companies.append(company_name)
                if is_supporting:
                    supporting_companies.append(company_name)
                parent_id = _top_parent(company_id, company_parents)
                parent_name = company_names.get(parent_id)
                if (is_dev or is_publisher) and parent_id != company_id and parent_name:
                    parent_companies.append(parent_name)

            image_id = cover_image_ids.get(row.get("cover") or "")
            cover_url = (
                COVER_URL_TEMPLATE.format(image_id=image_id) if image_id else None
            )

            released = row.get("first_release_date")
            first_release_date = date.fromisoformat(released[:10]) if released else None

            batch.extend(
                (
                    int(igdb_id),
                    steam_app_id,
                    row.get("name"),
                    list(dict.fromkeys(alternative_names.get(igdb_id, []))),
                    first_release_date,
                    game_types.get(row.get("game_type") or ""),
                    game_statuses.get(row.get("game_status") or ""),
                    _labels(row.get("genres"), genre_names),
                    _labels(row.get("themes"), theme_names),
                    _labels(row.get("game_modes"), game_mode_names),
                    _labels(row.get("player_perspectives"), perspective_names),
                    _labels(row.get("game_engines"), engine_names),
                    list(dict.fromkeys(developers)),
                    list(dict.fromkeys(publishers)),
                    list(dict.fromkeys(porting_companies)),
                    list(dict.fromkeys(supporting_companies)),
                    list(dict.fromkeys(developer_countries)),
                    list(dict.fromkeys(parent_companies)),
                    cover_url,
                )
                for steam_app_id in dict.fromkeys(steam_app_ids)
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
