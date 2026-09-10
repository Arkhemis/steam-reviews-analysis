"""Sélection des jeux de l'incrémental, jouée sur un vrai Postgres.

La requête ne porte que sur des sémantiques NULL : elle ne peut être vérifiée
qu'en base. Le test insère ses lignes dans une transaction annulée en sortie.
"""

import os
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from orchestration.steam.incremental import RELEVANT_APP_IDS

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

# app_id hors de l'espace Steam réel : aucune collision avec les données locales.
BACKFILLED_WITHOUT_CHECKPOINT = -1001
BACKFILLED_WITH_CHECKPOINT = -1002
ALREADY_COMPLETE = -1003
NEVER_BACKFILLED = -1004


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


def insert_census_row(
    conn: psycopg.Connection,
    app_id: int,
    *,
    total_reviews: int,
    total_reviews_backfilled: int,
    last_seen_timestamp_updated: int | None,
    backfilled: bool = True,
) -> None:
    conn.execute(
        """
        INSERT INTO raw.steam_review_counts (
            app_id, total_reviews, total_reviews_backfilled,
            last_backfill_at, last_seen_timestamp_updated
        )
        VALUES (%s, %s, %s, CASE WHEN %s THEN now() END, %s)
        """,
        (
            app_id,
            total_reviews,
            total_reviews_backfilled,
            backfilled,
            last_seen_timestamp_updated,
        ),
    )


def selected_app_ids(conn: psycopg.Connection) -> set[int]:
    return {row["app_id"] for row in conn.execute(RELEVANT_APP_IDS).fetchall()}


def selected_row(conn: psycopg.Connection, app_id: int) -> dict:
    return next(
        row
        for row in conn.execute(RELEVANT_APP_IDS).fetchall()
        if row["app_id"] == app_id
    )


def test_selects_backfilled_game_without_checkpoint(conn: psycopg.Connection) -> None:
    """Un jeu backfillé sans review n'a pas de checkpoint : il doit quand même
    être repris quand des reviews sortent (cf. Soul Chained, app_id 3544130)."""
    insert_census_row(
        conn,
        BACKFILLED_WITHOUT_CHECKPOINT,
        total_reviews=86,
        total_reviews_backfilled=0,
        last_seen_timestamp_updated=None,
    )

    assert BACKFILLED_WITHOUT_CHECKPOINT in selected_app_ids(conn)


def test_selects_backfilled_game_with_checkpoint(conn: psycopg.Connection) -> None:
    insert_census_row(
        conn,
        BACKFILLED_WITH_CHECKPOINT,
        total_reviews=120,
        total_reviews_backfilled=100,
        last_seen_timestamp_updated=1_700_000_000,
    )

    assert BACKFILLED_WITH_CHECKPOINT in selected_app_ids(conn)


def test_ignores_game_already_complete(conn: psycopg.Connection) -> None:
    insert_census_row(
        conn,
        ALREADY_COMPLETE,
        total_reviews=42,
        total_reviews_backfilled=42,
        last_seen_timestamp_updated=None,
    )

    assert ALREADY_COMPLETE not in selected_app_ids(conn)


def test_ignores_game_not_backfilled_yet(conn: psycopg.Connection) -> None:
    """Le backfill garde la main sur les jeux qu'il n'a pas encore traités."""
    insert_census_row(
        conn,
        NEVER_BACKFILLED,
        total_reviews=500,
        total_reviews_backfilled=0,
        last_seen_timestamp_updated=None,
        backfilled=False,
    )

    assert NEVER_BACKFILLED not in selected_app_ids(conn)


def test_exposes_census_total_to_the_paginator(conn: psycopg.Connection) -> None:
    """Sans checkpoint, le total recensé est la seule preuve d'arrêt disponible."""
    insert_census_row(
        conn,
        BACKFILLED_WITHOUT_CHECKPOINT,
        total_reviews=86,
        total_reviews_backfilled=0,
        last_seen_timestamp_updated=None,
    )

    row = selected_row(conn, BACKFILLED_WITHOUT_CHECKPOINT)

    assert row["total_reviews"] == 86
    assert row["last_seen_timestamp_updated"] == 0
