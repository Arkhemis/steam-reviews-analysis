"""Écriture des annonces, jouée sur un vrai ClickHouse."""

from orchestration.clickhouse import ClickHouseResource
from orchestration.steam.events import (
    MIN_TOTAL_REVIEWS,
    SELECT_APPS_SQL,
    event_to_row,
    has_known_event,
    write_events,
)


def event(gid: str, title: str) -> dict:
    return {"gid": gid, "event_name": title, "rtime32_start_time": 1_700_000_000}


def test_writes_only_new_or_changed_events(clickhouse: ClickHouseResource) -> None:
    first = [event_to_row(10, event("1", "a")), event_to_row(10, event("2", "b"))]
    assert write_events(clickhouse, first) == 2

    again = [event_to_row(10, event("1", "a")), event_to_row(10, event("2", "b2"))]
    assert write_events(clickhouse, again) == 1

    rows = clickhouse.query(
        "SELECT gid, JSONExtractString(payload, 'event_name') AS name "
        "FROM steam_events ORDER BY gid"
    )
    assert rows == [{"gid": "1", "name": "a"}, {"gid": "2", "name": "b2"}]


def test_large_batch_fits_in_one_request(clickhouse: ClickHouseResource) -> None:
    # 5000 couples (app_id, gid) dépassaient les 128 Kio d'un champ de formulaire.
    rows = [event_to_row(10, event(f"{gid:019d}", "a")) for gid in range(5000)]
    assert write_events(clickhouse, rows) == 5000
    assert write_events(clickhouse, rows) == 0


def test_same_gid_in_another_game_is_new(clickhouse: ClickHouseResource) -> None:
    write_events(clickhouse, [event_to_row(10, event("1", "a"))])

    batch = [event_to_row(10, event("1", "a")), event_to_row(20, event("1", "a"))]
    assert write_events(clickhouse, batch) == 1


def test_known_event_is_scoped_to_its_game(clickhouse: ClickHouseResource) -> None:
    write_events(clickhouse, [event_to_row(10, event("1", "a"))])

    assert has_known_event(clickhouse, 10, [event("1", "a"), event("9", "z")])
    assert not has_known_event(clickhouse, 20, [event("1", "a")])


def test_selects_games_above_threshold_and_flags_known_ones(
    clickhouse: ClickHouseResource,
) -> None:
    clickhouse.command(
        "INSERT INTO steam_review_counts (app_id, total_reviews, steam_count) "
        "VALUES (10, 500, NULL), (20, NULL, 200), (30, 50, 900)"
    )
    write_events(clickhouse, [event_to_row(10, event("1", "a"))])

    rows = clickhouse.query(SELECT_APPS_SQL, {"min_total_reviews": MIN_TOTAL_REVIEWS})

    # Le total prime sur le compteur GetItems, qui ne sert qu'en son absence.
    assert rows == [
        {"app_id": 10, "has_events": True},
        {"app_id": 20, "has_events": False},
    ]
