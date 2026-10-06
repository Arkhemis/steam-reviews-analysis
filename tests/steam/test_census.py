"""Sonde GetAppReviews du recensement : sélection et écriture jouées sur un vrai ClickHouse."""

from datetime import UTC, date, datetime, timedelta

from orchestration.clickhouse import ClickHouseResource
from orchestration.steam.census import (
    CENSUS_HOT_TOTAL_REVIEWS,
    DUE_APP_IDS_SQL,
    probe,
    probe_or_delisted,
    write_census,
)

# Multiple de 7 : BASE_APP_ID + d tombe le jour d.
BASE_APP_ID = 7 * 150_000_000


class FakeSteam:
    def __init__(self, page: dict, *, removed_from_store: bool = False) -> None:
        self.page = page
        self.removed_from_store = removed_from_store
        self.store_pages_checked: list[int] = []

    def get_all_reviews(self, app_id: int, *, num_per_page: int) -> dict:
        return self.page

    def is_removed_from_store(self, app_id: int) -> bool:
        self.store_pages_checked.append(app_id)
        return self.removed_from_store


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
    delisted: bool = False,
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
                delisted,
            )
        ],
        [
            "app_id",
            "total_reviews",
            "prev_total_reviews",
            "last_backfill_at",
            "checked_at",
            "is_delisted",
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


def test_empty_probe_of_a_game_removed_from_store_is_delisted() -> None:
    steam = FakeSteam({}, removed_from_store=True)

    assert probe_or_delisted(steam, 10, delisted=set()) == "delisted"


def test_empty_probe_of_a_game_still_on_store_keeps_the_previous_census() -> None:
    """Jeu bloqué dans le pays du VPS ou incident Steam : la page reste en 200."""
    steam = FakeSteam({}, removed_from_store=False)

    assert probe_or_delisted(steam, 10, delisted=set()) is None


def test_store_page_is_checked_once_per_delisting() -> None:
    steam = FakeSteam({}, removed_from_store=True)

    assert probe_or_delisted(steam, 10, delisted={10}) == "delisted"
    assert steam.store_pages_checked == []


def test_successful_probe_does_not_check_the_store_page() -> None:
    steam = FakeSteam({"query_summary": {"total_reviews": 3}})

    assert probe_or_delisted(steam, 10, delisted={10}) == {
        "total_reviews": 3,
        "latest_timestamp_updated": None,
    }
    assert steam.store_pages_checked == []


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


def test_probe_without_review_keeps_the_latest_update(
    clickhouse: ClickHouseResource,
) -> None:
    clickhouse.command(
        "INSERT INTO steam_review_counts (app_id, total_reviews, latest_timestamp_updated) "
        "VALUES (30, 3, 900)"
    )

    write_census(
        clickhouse, {30: {"total_reviews": 3, "latest_timestamp_updated": None}}, {30}
    )

    assert census(clickhouse)[30]["latest_timestamp_updated"] == 900


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


def delisting(clickhouse: ClickHouseResource) -> dict[int, dict]:
    rows = clickhouse.query(
        "SELECT app_id, total_reviews, is_delisted, "
        "checked_at > now() - INTERVAL 1 MINUTE AS checked_now FROM steam_review_counts"
    )
    return {row.pop("app_id"): row for row in rows}


def test_write_marks_delisted_games_and_keeps_their_census(
    clickhouse: ClickHouseResource,
) -> None:
    insert_game(clickhouse, 50, total_reviews=12_000, checked_days_ago=3)
    known = {50}

    write_census(clickhouse, {}, known, delisted=[50, 60])

    assert delisting(clickhouse) == {
        50: {"total_reviews": 12_000, "is_delisted": True, "checked_now": True},
        60: {"total_reviews": None, "is_delisted": True, "checked_now": True},
    }
    assert known == {50, 60}


def test_successful_probe_relists_the_game(clickhouse: ClickHouseResource) -> None:
    insert_game(clickhouse, 70, delisted=True)

    write_census(clickhouse, {70: {"total_reviews": 101}}, {70})

    assert delisting(clickhouse)[70]["is_delisted"] is False


def test_delisted_games_are_probed_on_their_day_only(
    clickhouse: ClickHouseResource,
) -> None:
    today = app_id_for_day(clickhouse, today=True)
    base = app_id_for_day(clickhouse, today=False)
    hot, moved, not_backfilled, stale = (base + 7 * i for i in range(4))
    insert_game(
        clickhouse, today, total_reviews=CENSUS_HOT_TOTAL_REVIEWS, delisted=True
    )
    insert_game(
        clickhouse,
        hot,
        total_reviews=CENSUS_HOT_TOTAL_REVIEWS,
        prev_total_reviews=CENSUS_HOT_TOTAL_REVIEWS,
        delisted=True,
    )
    insert_game(clickhouse, moved, total_reviews=101, delisted=True)
    insert_game(clickhouse, not_backfilled, backfilled=False, delisted=True)
    insert_game(clickhouse, stale, checked_days_ago=9, delisted=True)

    assert due(clickhouse) == {today, stale}
