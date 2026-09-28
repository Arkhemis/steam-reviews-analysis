"""Écritures du backfill et du recomptage de l'incrémental, jouées sur un vrai ClickHouse."""

import json

from orchestration.clickhouse import ClickHouseResource
from orchestration.steam.backfill import (
    insert_reviews,
    mark_backfilled,
    reviews_to_rows,
    write_summaries,
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
        "SELECT app_id, total_reviews, prev_total_reviews, review_score_desc, "
        "total_reviews_backfilled, last_seen_timestamp_updated, synced_steam_count, "
        "last_backfill_at IS NOT NULL AS backfilled FROM steam_review_counts"
    )
    return {row.pop("app_id"): row for row in rows}


def test_summary_and_mark_update_each_game_with_its_own_values(
    clickhouse: ClickHouseResource,
) -> None:
    clickhouse.command(
        "INSERT INTO steam_review_counts (app_id, total_reviews, steam_count, "
        "last_seen_timestamp_updated) VALUES (10, 3, 30, 900), (20, NULL, 40, NULL)"
    )

    write_summaries(
        clickhouse,
        {
            10: {"total_reviews": 5, "review_score_desc": "Positive"},
            20: {"total_reviews": 7, "review_score_desc": None},
        },
    )
    mark_backfilled(clickhouse, [(10, 5, 800), (20, 7, 1200)])

    assert counts(clickhouse) == {
        10: {
            "total_reviews": 5,
            "prev_total_reviews": 3,
            "review_score_desc": "Positive",
            "total_reviews_backfilled": 5,
            # Le checkpoint ne recule jamais.
            "last_seen_timestamp_updated": 900,
            "synced_steam_count": 30,
            "backfilled": True,
        },
        20: {
            "total_reviews": 7,
            "prev_total_reviews": None,
            "review_score_desc": None,
            "total_reviews_backfilled": 7,
            "last_seen_timestamp_updated": 1200,
            "synced_steam_count": 40,
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


def test_recount_fixes_only_drifted_games(clickhouse: ClickHouseResource) -> None:
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
