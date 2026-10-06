"""Écritures du backfill et du recomptage de l'incrémental, jouées sur un vrai ClickHouse."""

import json

import pytest

from orchestration.clickhouse import ClickHouseResource
from orchestration.steam.backfill import (
    ABSENT_STEAM_IDS,
    insert_reviews,
    mark_backfilled,
    reviews_to_rows,
)
from orchestration.steam.incremental import recount_backfilled


def review(recommendation_id: int, timestamp_updated: int) -> dict:
    return {
        "recommendationid": str(recommendation_id),
        "timestamp_created": 1_700_000_000,
        "timestamp_updated": timestamp_updated,
        "review": "ok",
    }


def counts(clickhouse: ClickHouseResource) -> dict[int, dict]:
    rows = clickhouse.query(
        "SELECT app_id, total_reviews_backfilled, last_seen_timestamp_updated, "
        "last_backfill_at IS NOT NULL AS backfilled FROM steam_review_counts"
    )
    return {row.pop("app_id"): row for row in rows}


def test_mark_updates_each_game_with_its_own_values(
    clickhouse: ClickHouseResource,
) -> None:
    clickhouse.command(
        "INSERT INTO steam_review_counts (app_id, last_seen_timestamp_updated) "
        "VALUES (10, 900), (20, NULL)"
    )

    mark_backfilled(clickhouse, [(10, 5, 800), (20, 7, 1200)])

    assert counts(clickhouse) == {
        10: {
            "total_reviews_backfilled": 5,
            # Le checkpoint ne recule jamais.
            "last_seen_timestamp_updated": 900,
            "backfilled": True,
        },
        20: {
            "total_reviews_backfilled": 7,
            "last_seen_timestamp_updated": 1200,
            "backfilled": True,
        },
    }


def test_reinserted_versions_are_deduplicated(clickhouse: ClickHouseResource) -> None:
    """Un lot rejoué après un arrêt réinsère les mêmes versions."""
    rows = reviews_to_rows(10, [review(1, 100), review(1, 200), review(2, 100)])
    insert_reviews(clickhouse, rows)
    insert_reviews(clickhouse, rows)

    stored = clickhouse.query(
        "SELECT recommendation_id, timestamp_updated, payload.review::String AS text "
        "FROM steam_reviews ORDER BY recommendation_id, timestamp_updated"
    )

    assert [(r["recommendation_id"], r["timestamp_updated"]) for r in stored] == [
        (1, 100),
        (1, 200),
        (2, 100),
    ]
    assert json.loads(rows[0][2])["review"] == stored[0]["text"]


def test_recount_fixes_only_drifted_games(
    clickhouse: ClickHouseResource, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Un jeu par UPDATE : les corrections partent par tranches.
    monkeypatch.setattr("orchestration.steam.incremental.PARAM_BATCH_SIZE", 1)
    clickhouse.command(
        "INSERT INTO steam_review_counts (app_id, total_reviews_backfilled, last_backfill_at) "
        "VALUES (10, 2, now64(6)), (20, 9, now64(6)), (30, NULL, now64(6)), (40, 5, NULL)"
    )
    insert_reviews(
        clickhouse,
        reviews_to_rows(10, [review(1, 100), review(1, 200), review(2, 100)]),
    )
    insert_reviews(clickhouse, reviews_to_rows(20, [review(3, 100)]))

    assert recount_backfilled(clickhouse) == 2

    assert {
        app_id: row["total_reviews_backfilled"]
        for app_id, row in counts(clickhouse).items()
    } == {
        # Deux versions d'une même review ne comptent qu'une fois.
        10: 2,
        20: 1,
        # Backfillé sans aucune review stockée : retombe à 0.
        30: 0,
        # Jamais backfillé : le recomptage ne le touche pas.
        40: 5,
    }


def test_backfill_skips_games_removed_from_store(
    clickhouse: ClickHouseResource,
) -> None:
    clickhouse.command(
        "INSERT INTO steam_review_counts (app_id, total_reviews, is_delisted) "
        "VALUES (10, 5, false), (20, 5, true)"
    )

    assert [row["app_id"] for row in clickhouse.query(ABSENT_STEAM_IDS)] == [10]
