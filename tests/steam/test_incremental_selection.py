"""Sélection des jeux de l'incrémental, jouée sur un vrai ClickHouse."""

from datetime import UTC, datetime

from orchestration.clickhouse import ClickHouseResource
from orchestration.steam.incremental import RELEVANT_APP_IDS


def insert_census_row(
    clickhouse: ClickHouseResource,
    app_id: int,
    *,
    latest_timestamp_updated: int | None,
    last_seen_timestamp_updated: int | None = 1_700_000_000,
    total_reviews: int | None = 100,
    backfilled: bool = True,
) -> None:
    clickhouse.insert(
        "steam_review_counts",
        [
            (
                app_id,
                total_reviews,
                datetime.now(UTC) if backfilled else None,
                last_seen_timestamp_updated,
                latest_timestamp_updated,
            )
        ],
        [
            "app_id",
            "total_reviews",
            "last_backfill_at",
            "last_seen_timestamp_updated",
            "latest_timestamp_updated",
        ],
    )


def selected_rows(clickhouse: ClickHouseResource) -> dict[int, dict]:
    return {row["app_id"]: row for row in clickhouse.query(RELEVANT_APP_IDS)}


def test_selects_game_updated_after_its_checkpoint(
    clickhouse: ClickHouseResource,
) -> None:
    insert_census_row(clickhouse, 10, latest_timestamp_updated=1_700_000_001)

    assert 10 in selected_rows(clickhouse)


def test_ignores_game_at_its_checkpoint(clickhouse: ClickHouseResource) -> None:
    insert_census_row(clickhouse, 10, latest_timestamp_updated=1_700_000_000)

    assert 10 not in selected_rows(clickhouse)


def test_ignores_game_never_probed(clickhouse: ClickHouseResource) -> None:
    insert_census_row(clickhouse, 10, latest_timestamp_updated=None)

    assert 10 not in selected_rows(clickhouse)


def test_ignores_game_not_backfilled_yet(clickhouse: ClickHouseResource) -> None:
    """Le backfill garde la main sur les jeux qu'il n'a pas encore traités."""
    insert_census_row(
        clickhouse, 10, latest_timestamp_updated=1_800_000_000, backfilled=False
    )

    assert 10 not in selected_rows(clickhouse)


def test_selects_first_reviews_of_a_game_backfilled_without_any(
    clickhouse: ClickHouseResource,
) -> None:
    """Soul Chained (3544130) : backfillé sans review, puis ses premières reviews arrivent."""
    insert_census_row(
        clickhouse,
        10,
        latest_timestamp_updated=1_700_000_000,
        last_seen_timestamp_updated=None,
        total_reviews=86,
    )

    row = selected_rows(clickhouse)[10]

    # Sans checkpoint, le total connu est la preuve d'arrêt de repli.
    assert row["total_reviews"] == 86
    assert row["last_seen_timestamp_updated"] == 0
