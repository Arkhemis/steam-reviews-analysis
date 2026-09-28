"""Base ClickHouse jetable pour les tests qui ont besoin d'un vrai serveur.

Le DDL de raw (db/clickhouse/init.sql) est rejoué dans une base `test_…`,
supprimée en sortie : les données locales ne sont jamais touchées.
"""

import os
import uuid
from pathlib import Path

import pytest

from orchestration.clickhouse import ClickHouseResource

ROOT = Path(__file__).resolve().parents[1]
INIT_SQL = ROOT / "db" / "clickhouse" / "init.sql"


def clickhouse_settings() -> dict[str, str]:
    """Variables CLICKHOUSE_* de l'environnement, complétées par le .env du projet."""
    settings = {k: v for k, v in os.environ.items() if k.startswith("CLICKHOUSE_")}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip().startswith("CLICKHOUSE_"):
                settings.setdefault(key.strip(), value.strip().strip("'\""))
    return settings


def raw_ddl(database: str) -> list[str]:
    """Instructions de init.sql, la base raw remplacée par `database`."""
    sql = INIT_SQL.read_text().replace("raw.", f"{database}.")
    sql = sql.replace("DATABASE IF NOT EXISTS raw", f"DATABASE {database}")
    lines = [line for line in sql.splitlines() if not line.lstrip().startswith("--")]
    return [stmt for stmt in "\n".join(lines).split(";") if stmt.strip()]


@pytest.fixture
def clickhouse():
    settings = clickhouse_settings()
    if "CLICKHOUSE_PASSWORD" not in settings:
        pytest.skip("variables ClickHouse absentes")
    database = f"test_{uuid.uuid4().hex[:12]}"
    connection = {
        "host": settings.get("CLICKHOUSE_HOST", "localhost"),
        "port": int(settings.get("CLICKHOUSE_PORT", 8123)),
        "user": settings.get("CLICKHOUSE_USER", "default"),
        "password": settings["CLICKHOUSE_PASSWORD"],
    }
    admin = ClickHouseResource(**connection, database="default")
    try:
        admin.command("SELECT 1")
    except Exception as exc:
        pytest.skip(f"ClickHouse injoignable : {exc}")
    for stmt in raw_ddl(database):
        admin.command(stmt)
    try:
        yield ClickHouseResource(**connection, database=database)
    finally:
        admin.command(f"DROP DATABASE IF EXISTS {database}")
