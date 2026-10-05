"""Sonde GetAppReviews du recensement : sélection et écriture jouées sur un vrai ClickHouse."""

from datetime import UTC, date, datetime, timedelta

from orchestration.clickhouse import ClickHouseResource
from orchestration.steam.census import (
    CENSUS_HOT_TOTAL_REVIEWS,
    DUE_APP_IDS_SQL,
    probe,
    write_census,
)

# Multiple de 7 : BASE_APP_ID + d tombe le jour d.
BASE_APP_ID = 7 * 150_000_000


class FakeSteam:
    def __init__(self, page: dict) -> None:
        self.page = page

    def get_all_reviews(self, app_id: int, *, num_per_page: int) -> dict:
        return self.page


def census(clickhouse: ClickHouseResource) -> dict[int, dict]:
    rows = clickhouse.query(
        "SELECT app_id, total_reviews, prev_total_reviews, review_score_desc, "
        "latest_timestamp_updated FROM steam_review_counts"
    )
    return {row.pop("app_id"): row for row in rows}


def app_id_for_day(clickhouse: ClickHouseResource, *, today: bool) -> int:
    """Un app_id dont le jour de sonde est (ou n'est pas) aujourd'hui."""
    dow = clickhouse.query("SELECT toDayOfWeek(now()) % 7 AS dow")[0]["dow"]
    return BASE_APP_ID + (dow if today else (dow + 1) % 7)


def insert_game(
    clickhouse: ClickHouseResource,
    app_id: int,
    *,
    total_reviews: int | None = 100,
    prev_total_reviews: int | None = 100,
    backfilled: bool = True,
    checked_days_ago: int = 1,
    release: date | None = None,
    in_census: bool = True,
) -> None:
    clickhouse.insert(
        "igdb_games",
        [(app_id, app_id, release)],
        ["igdb_id", "steam_app_id", "first_release_date"],
    )
    if not in_census:
        return
    now = datetime.now(UTC)
    clickhouse.insert(
        "steam_review_counts",
        [
            (
                app_id,
                total_reviews,
                prev_total_reviews,
                now if backfilled else None,
                now - timedelta(days=checked_days_ago),
            )
        ],
        [
            "app_id",
            "total_reviews",
            "prev_total_reviews",
            "last_backfill_at",
            "checked_at",
        ],
    )


def due(clickhouse: ClickHouseResource) -> set[int]:
    rows = clickhouse.query(
        DUE_APP_IDS_SQL, {"hot_total_reviews": CENSUS_HOT_TOTAL_REVIEWS}
    )
    return {row["app_id"] for row in rows}


def test_probe_reads_totals_and_latest_update() -> None:
    steam = FakeSteam(
        {
            "query_summary": {"total_reviews": 12, "review_score_desc": "Positive"},
            "reviews": [{"timestamp_updated": 1_700_000_500}],
        }
    )

    assert probe(steam, 10) == {
        "total_reviews": 12,
        "review_score_desc": "Positive",
        "latest_timestamp_updated": 1_700_000_500,
    }


def test_probe_of_a_game_without_review_has_no_latest_update() -> None:
    steam = FakeSteam({"query_summary": {"total_reviews": 0}})

    assert probe(steam, 10) == {"total_reviews": 0, "latest_timestamp_updated": None}


def test_probe_without_summary_keeps_the_previous_census() -> None:
    assert probe(FakeSteam({}), 10) is None


def test_write_inserts_new_games_and_shifts_previous_total(
    clickhouse: ClickHouseResource,
) -> None:
    clickhouse.command(
        "INSERT INTO steam_review_counts (app_id, total_reviews, latest_timestamp_updated) "
        "VALUES (10, 3, 900)"
    )
    known = {10}

    write_census(
        clickhouse,
        {
            10: {
                "total_reviews": 5,
                "review_score_desc": "Positive",
                "latest_timestamp_updated": 950,
            },
            20: {"total_reviews": 0, "latest_timestamp_updated": None},
        },
        known,
    )

    assert census(clickhouse) == {
        10: {
            "total_reviews": 5,
            "prev_total_reviews": 3,
            "review_score_desc": "Positive",
            "latest_timestamp_updated": 950,
        },
        20: {
            "total_reviews": 0,
            "prev_total_reviews": None,
            "review_score_desc": None,
            "latest_timestamp_updated": None,
        },
    }
    assert known == {10, 20}


def test_second_write_does_not_duplicate_new_games(
    clickhouse: ClickHouseResource,
) -> None:
    known: set[int] = set()

    write_census(clickhouse, {40: {"total_reviews": 1}}, known)
    write_census(clickhouse, {40: {"total_reviews": 2}}, known)

    rows = clickhouse.query("SELECT app_id, total_reviews FROM steam_review_counts")
    assert rows == [{"app_id": 40, "total_reviews": 2}]


def test_quiet_small_game_is_probed_on_its_day_only(
    clickhouse: ClickHouseResource,
) -> None:
    today = app_id_for_day(clickhouse, today=True)
    other_day = app_id_for_day(clickhouse, today=False)
    insert_game(clickhouse, today)
    insert_game(clickhouse, other_day)

    selected = due(clickhouse)

    assert today in selected
    assert other_day not in selected


def test_probes_every_night_the_games_that_need_it(
    clickhouse: ClickHouseResource,
) -> None:
    base = app_id_for_day(clickhouse, today=False)
    unknown, not_backfilled, hot, moved, stale, new_release = (
        base + 7 * i for i in range(6)
    )
    insert_game(clickhouse, unknown, in_census=False)
    insert_game(clickhouse, not_backfilled, backfilled=False)
    insert_game(
        clickhouse,
        hot,
        total_reviews=CENSUS_HOT_TOTAL_REVIEWS,
        prev_total_reviews=CENSUS_HOT_TOTAL_REVIEWS,
    )
    insert_game(clickhouse, moved, total_reviews=101)
    insert_game(clickhouse, stale, checked_days_ago=9)
    insert_game(
        clickhouse, new_release, release=datetime.now(UTC).date() - timedelta(days=2)
    )

    assert due(clickhouse) == {
        unknown,
        not_backfilled,
        hot,
        moved,
        stale,
        new_release,
    }
