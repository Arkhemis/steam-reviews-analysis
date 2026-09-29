"""Écriture du recensement GetItems, jouée sur un vrai ClickHouse."""

from orchestration.clickhouse import ClickHouseResource
from orchestration.steam.census import write_steam_counts


def census(clickhouse: ClickHouseResource) -> dict[int, dict]:
    rows = clickhouse.query(
        "SELECT app_id, steam_count, synced_steam_count, "
        "steam_count_checked_at IS NOT NULL AS checked FROM steam_review_counts"
    )
    return {row.pop("app_id"): row for row in rows}


def test_inserts_new_games_and_updates_known_ones(
    clickhouse: ClickHouseResource,
) -> None:
    clickhouse.command(
        "INSERT INTO steam_review_counts (app_id, steam_count, synced_steam_count, last_backfill_at) "
        "VALUES (10, 5, 5, now64(6)), (20, 5, NULL, NULL), (30, 5, NULL, now64(6))"
    )
    known = {10, 20, 30}

    write_steam_counts(clickhouse, [(10, 7), (20, 8), (30, 9), (40, 1)], known)

    assert census(clickhouse) == {
        # Déjà synchronisé : seul le compteur du jour bouge.
        10: {"steam_count": 7, "synced_steam_count": 5, "checked": True},
        # Jamais backfillé : le backfill fixera le point de départ.
        20: {"steam_count": 8, "synced_steam_count": None, "checked": True},
        # Backfillé avant le recensement : le compteur du jour sert de départ.
        30: {"steam_count": 9, "synced_steam_count": 9, "checked": True},
        40: {"steam_count": 1, "synced_steam_count": None, "checked": True},
    }
    assert known == {10, 20, 30, 40}


def test_second_pass_does_not_duplicate_new_games(
    clickhouse: ClickHouseResource,
) -> None:
    known: set[int] = set()

    write_steam_counts(clickhouse, [(40, 1)], known)
    write_steam_counts(clickhouse, [(40, 2)], known)

    rows = clickhouse.query("SELECT app_id, steam_count FROM steam_review_counts")
    assert rows == [{"app_id": 40, "steam_count": 2}]
