"""Sélection des jeux de l'incrémental, jouée sur un vrai Postgres.

La requête repose sur des sémantiques NULL et sur le modulo de Postgres : elle
ne peut être vérifiée qu'en base. Le test insère ses lignes dans une transaction annulée en sortie.
"""

import os
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from orchestration.steam.incremental import RELEVANT_APP_IDS, ROTATION_STEAM_COUNT

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def postgres_settings() -> dict[str, str]:
    """Variables POSTGRES_* de l'environnement, complétées par le .env du projet."""
    settings = {k: v for k, v in os.environ.items() if k.startswith("POSTGRES_")}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            settings.setdefault(key.strip(), value.strip().strip("'\""))
    return settings


@pytest.fixture
def conn():
    settings = postgres_settings()
    missing = {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"} - settings.keys()
    if missing:
        pytest.skip(f"variables Postgres absentes : {sorted(missing)}")
    try:
        connection = psycopg.connect(
            host=settings.get("POSTGRES_HOST", "localhost"),
            port=int(settings.get("POSTGRES_PORT", 5432)),
            user=settings["POSTGRES_USER"],
            password=settings["POSTGRES_PASSWORD"],
            dbname=settings["POSTGRES_DB"],
            row_factory=dict_row,
        )
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres injoignable : {exc}")
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


# app_id hors de l'espace Steam réel (> 10^9) : aucune collision avec les données
# locales. Multiple de 7 et positif, pour que BASE_APP_ID + d tombe le jour d.
BASE_APP_ID = 7 * 150_000_000


def insert_census_row(
    conn: psycopg.Connection,
    app_id: int,
    *,
    steam_count: int | None,
    synced_steam_count: int | None,
    total_reviews: int | None = 100,
    last_seen_timestamp_updated: int | None = 1_700_000_000,
    backfilled: bool = True,
) -> None:
    conn.execute(
        """
        INSERT INTO raw.steam_review_counts (
            app_id, total_reviews, steam_count, synced_steam_count,
            last_backfill_at, last_seen_timestamp_updated
        )
        VALUES (%s, %s, %s, %s, CASE WHEN %s THEN now() END, %s)
        """,
        (
            app_id,
            total_reviews,
            steam_count,
            synced_steam_count,
            backfilled,
            last_seen_timestamp_updated,
        ),
    )


def selected_rows(conn: psycopg.Connection) -> dict[int, dict]:
    rows = conn.execute(
        RELEVANT_APP_IDS, {"rotation_steam_count": ROTATION_STEAM_COUNT}
    ).fetchall()
    return {row["app_id"]: row for row in rows}


def app_id_for_rotation(conn: psycopg.Connection, *, today: bool) -> int:
    """Un app_id dont le jour de rotation est (ou n'est pas) aujourd'hui."""
    dow = conn.execute("SELECT extract(dow FROM now())::int AS dow").fetchone()["dow"]
    offset = dow if today else (dow + 1) % 7
    return BASE_APP_ID + offset


def test_selects_game_whose_steam_count_moved(conn: psycopg.Connection) -> None:
    app_id = app_id_for_rotation(conn, today=False)
    insert_census_row(conn, app_id, steam_count=120, synced_steam_count=100)

    assert app_id in selected_rows(conn)


def test_ignores_game_that_did_not_move(conn: psycopg.Connection) -> None:
    app_id = app_id_for_rotation(conn, today=False)
    insert_census_row(conn, app_id, steam_count=100, synced_steam_count=100)

    assert app_id not in selected_rows(conn)


def test_selects_first_count_of_a_game_never_synced(conn: psycopg.Connection) -> None:
    """Soul Chained (3544130) : backfillé sans review, puis ses premières reviews arrivent."""
    app_id = app_id_for_rotation(conn, today=False)
    insert_census_row(
        conn,
        app_id,
        steam_count=86,
        synced_steam_count=None,
        total_reviews=0,
        last_seen_timestamp_updated=None,
    )

    assert app_id in selected_rows(conn)


def test_ignores_game_not_backfilled_yet(conn: psycopg.Connection) -> None:
    """Le backfill garde la main sur les jeux qu'il n'a pas encore traités."""
    app_id = app_id_for_rotation(conn, today=False)
    insert_census_row(
        conn, app_id, steam_count=500, synced_steam_count=None, backfilled=False
    )

    assert app_id not in selected_rows(conn)


def test_rotates_big_quiet_games_once_a_week(conn: psycopg.Connection) -> None:
    """Sans mouvement, un gros jeu revient le jour de sa rotation, et seulement ce jour-là."""
    today = app_id_for_rotation(conn, today=True)
    other_day = app_id_for_rotation(conn, today=False)
    for app_id in (today, other_day):
        insert_census_row(
            conn,
            app_id,
            steam_count=ROTATION_STEAM_COUNT,
            synced_steam_count=ROTATION_STEAM_COUNT,
        )

    selected = selected_rows(conn)

    assert today in selected
    assert other_day not in selected


def test_exposes_total_and_checkpoint_to_the_paginator(
    conn: psycopg.Connection,
) -> None:
    """Sans checkpoint, le total connu est la preuve d'arrêt de repli."""
    app_id = app_id_for_rotation(conn, today=False)
    insert_census_row(
        conn,
        app_id,
        steam_count=86,
        synced_steam_count=0,
        total_reviews=86,
        last_seen_timestamp_updated=None,
    )

    row = selected_rows(conn)[app_id]

    assert row["total_reviews"] == 86
    assert row["last_seen_timestamp_updated"] == 0
