"""Sélection des jeux de l'incrémental, jouée sur un vrai ClickHouse.

La requête repose sur des sémantiques NULL et sur le jour de la semaine : elle
ne peut être vérifiée qu'en base. Le test écrit dans une base jetable (cf. conftest).
"""

from datetime import UTC, datetime

from orchestration.clickhouse import ClickHouseResource
from orchestration.steam.incremental import RELEVANT_APP_IDS, ROTATION_STEAM_COUNT

# app_id hors de l'espace Steam réel (> 10^9) : aucune collision avec les données
# locales. Multiple de 7 et positif, pour que BASE_APP_ID + d tombe le jour d.
BASE_APP_ID = 7 * 150_000_000


def insert_census_row(
    clickhouse: ClickHouseResource,
    app_id: int,
    *,
    steam_count: int | None,
    synced_steam_count: int | None,
    total_reviews: int | None = 100,
    last_seen_timestamp_updated: int | None = 1_700_000_000,
    backfilled: bool = True,
) -> None:
    clickhouse.insert(
        "steam_review_counts",
        [
            (
                app_id,
                total_reviews,
                steam_count,
                synced_steam_count,
                datetime.now(UTC) if backfilled else None,
                last_seen_timestamp_updated,
            )
        ],
        [
            "app_id",
            "total_reviews",
            "steam_count",
            "synced_steam_count",
            "last_backfill_at",
            "last_seen_timestamp_updated",
        ],
    )


def selected_rows(clickhouse: ClickHouseResource) -> dict[int, dict]:
    rows = clickhouse.query(
        RELEVANT_APP_IDS, {"rotation_steam_count": ROTATION_STEAM_COUNT}
    )
    return {row["app_id"]: row for row in rows}


def app_id_for_rotation(clickhouse: ClickHouseResource, *, today: bool) -> int:
    """Un app_id dont le jour de rotation est (ou n'est pas) aujourd'hui."""
    dow = clickhouse.query("SELECT toDayOfWeek(now()) % 7 AS dow")[0]["dow"]
    offset = dow if today else (dow + 1) % 7
    return BASE_APP_ID + offset


def test_selects_game_whose_steam_count_moved(clickhouse: ClickHouseResource) -> None:
    app_id = app_id_for_rotation(clickhouse, today=False)
    insert_census_row(clickhouse, app_id, steam_count=120, synced_steam_count=100)

    assert app_id in selected_rows(clickhouse)


def test_ignores_game_that_did_not_move(clickhouse: ClickHouseResource) -> None:
    app_id = app_id_for_rotation(clickhouse, today=False)
    insert_census_row(clickhouse, app_id, steam_count=100, synced_steam_count=100)

    assert app_id not in selected_rows(clickhouse)


def test_selects_first_count_of_a_game_never_synced(
    clickhouse: ClickHouseResource,
) -> None:
    """Soul Chained (3544130) : backfillé sans review, puis ses premières reviews arrivent."""
    app_id = app_id_for_rotation(clickhouse, today=False)
    insert_census_row(
        clickhouse,
        app_id,
        steam_count=86,
        synced_steam_count=None,
        total_reviews=0,
        last_seen_timestamp_updated=None,
    )

    assert app_id in selected_rows(clickhouse)


def test_ignores_game_not_backfilled_yet(clickhouse: ClickHouseResource) -> None:
    """Le backfill garde la main sur les jeux qu'il n'a pas encore traités."""
    app_id = app_id_for_rotation(clickhouse, today=False)
    insert_census_row(
        clickhouse, app_id, steam_count=500, synced_steam_count=None, backfilled=False
    )

    assert app_id not in selected_rows(clickhouse)


def test_rotates_big_quiet_games_once_a_week(clickhouse: ClickHouseResource) -> None:
    """Sans mouvement, un gros jeu revient le jour de sa rotation, et seulement ce jour-là."""
    today = app_id_for_rotation(clickhouse, today=True)
    other_day = app_id_for_rotation(clickhouse, today=False)
    for app_id in (today, other_day):
        insert_census_row(
            clickhouse,
            app_id,
            steam_count=ROTATION_STEAM_COUNT,
            synced_steam_count=ROTATION_STEAM_COUNT,
        )

    selected = selected_rows(clickhouse)

    assert today in selected
    assert other_day not in selected


def test_rotates_games_without_steam_count_once_a_week(
    clickhouse: ClickHouseResource,
) -> None:
    """Sans compteur GetItems, le mouvement est invisible : seule la rotation les reprend."""
    today = app_id_for_rotation(clickhouse, today=True)
    other_day = app_id_for_rotation(clickhouse, today=False)
    for app_id in (today, other_day):
        insert_census_row(clickhouse, app_id, steam_count=None, synced_steam_count=None)

    selected = selected_rows(clickhouse)

    assert today in selected
    assert other_day not in selected


def test_exposes_total_and_checkpoint_to_the_paginator(
    clickhouse: ClickHouseResource,
) -> None:
    """Sans checkpoint, le total connu est la preuve d'arrêt de repli."""
    app_id = app_id_for_rotation(clickhouse, today=False)
    insert_census_row(
        clickhouse,
        app_id,
        steam_count=86,
        synced_steam_count=0,
        total_reviews=86,
        last_seen_timestamp_updated=None,
    )

    row = selected_rows(clickhouse)[app_id]

    assert row["total_reviews"] == 86
    assert row["last_seen_timestamp_updated"] == 0
