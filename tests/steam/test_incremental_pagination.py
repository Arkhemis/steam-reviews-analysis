"""Arrêt de la pagination incrémentale d'un jeu sans checkpoint."""

from typing import Any

import pytest

from orchestration.steam import incremental
from orchestration.steam.backfill import SUMMARY_RETRIES
from orchestration.steam.incremental import NewReviewPages, sync_app_reviews

PAGE_CURSOR = "page2"


def summary(total_reviews: int | None) -> dict[str, Any]:
    """query_summary de la page 1, absent quand `total_reviews` est None."""
    if total_reviews is None:
        return {}
    return {"query_summary": {"total_reviews": total_reviews, "review_score": 6}}


class FakeSteam:
    """Sert une page de reviews, puis la fin de pagination annoncée par Steam."""

    def __init__(
        self, reviews: list[dict[str, Any]], total_reviews: int | None = None
    ) -> None:
        self.reviews = reviews
        self.total_reviews = total_reviews
        self.calls: list[str] = []

    def get_all_reviews(self, app_id: int, *, cursor: str, language: str) -> dict:
        self.calls.append(cursor)
        if cursor == "*":
            return {
                "reviews": self.reviews,
                "cursor": PAGE_CURSOR,
                **summary(self.total_reviews),
            }
        return {"reviews": [], "cursor": None}


@pytest.fixture
def slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    delays: list[float] = []
    monkeypatch.setattr(incremental.time, "sleep", delays.append)
    return delays


def reviews(count: int) -> list[dict[str, Any]]:
    return [
        {
            "recommendationid": str(1000 + i),
            "timestamp_created": 1_700_000_000 + i,
            "timestamp_updated": 1_700_000_000 + i,
        }
        for i in range(count)
    ]


def test_stops_at_once_when_census_total_is_reached(slept: list[float]) -> None:
    """86 reviews servies pour 86 recensées : la fin annoncée est vraie."""
    steam = FakeSteam(reviews(86), total_reviews=86)
    pages = NewReviewPages(
        steam, app_id=3544130, last_seen_timestamp_updated=0, total_reviews=86
    )

    served = [review for page in pages for review in page]

    assert len(served) == 86
    assert pages.reached_checkpoint
    assert slept == []
    assert steam.calls == ["*", PAGE_CURSOR]


def test_retries_when_census_total_is_far_from_reached(slept: list[float]) -> None:
    """86 reviews servies pour 1000 recensées : la fin annoncée est suspecte."""
    steam = FakeSteam(reviews(86), total_reviews=1000)
    pages = NewReviewPages(
        steam, app_id=3544130, last_seen_timestamp_updated=0, total_reviews=1000
    )

    list(pages)

    assert slept == [5.0, 10.0, 20.0, 40.0, 80.0, 160.0]


def test_page_one_total_replaces_the_stale_one(slept: list[float]) -> None:
    """La base croit à 1000 reviews, Steam en annonce 86 : on croit Steam."""
    steam = FakeSteam(reviews(86), total_reviews=86)
    pages = NewReviewPages(
        steam, app_id=3544130, last_seen_timestamp_updated=0, total_reviews=1000
    )

    list(pages)

    assert pages.total_reviews == 86
    assert pages.summary["review_score"] == 6
    assert slept == []


def test_replays_page_one_when_the_summary_is_missing(slept: list[float]) -> None:
    """Sans résumé, on garde le total connu après quelques relances de la page 1."""
    steam = FakeSteam(reviews(86), total_reviews=None)
    pages = NewReviewPages(
        steam, app_id=3544130, last_seen_timestamp_updated=0, total_reviews=86
    )

    list(pages)

    assert pages.summary is None
    assert steam.calls == ["*"] * (SUMMARY_RETRIES + 1) + [PAGE_CURSOR]
    assert pages.reached_checkpoint


class FakeClickHouse:
    def __init__(self) -> None:
        self.inserted: list[tuple] = []
        self.checkpoints: list[dict] = []

    def insert(self, table: str, rows: list[tuple], column_names: list[str]) -> None:
        self.inserted.extend(rows)

    def command(self, sql: str, parameters: dict) -> None:
        self.checkpoints.append(parameters)


def test_sync_hands_the_census_total_to_the_paginator(slept: list[float]) -> None:
    """Le total recensé doit descendre jusqu'au paginateur, sinon rien ne change."""
    steam = FakeSteam(reviews(86), total_reviews=None)
    clickhouse = FakeClickHouse()

    result = sync_app_reviews(
        steam,
        clickhouse,
        app_id=3544130,
        last_seen_timestamp_updated=0,
        total_reviews=86,
    )

    assert result.reached_checkpoint
    assert len(clickhouse.inserted) == 86
    assert slept == []


def test_sync_keeps_the_checkpoint_when_it_is_missed(
    slept: list[float],
) -> None:
    """Pagination ratée : le checkpoint ne bouge pas."""
    steam = FakeSteam(reviews(86), total_reviews=1000)
    clickhouse = FakeClickHouse()

    # Checkpoint plus ancien que toutes les reviews servies : jamais rejoint.
    result = sync_app_reviews(
        steam,
        clickhouse,
        app_id=3544130,
        last_seen_timestamp_updated=1_600_000_000,
    )

    assert not result.reached_checkpoint
    assert result.versions_inserted == 0
    # Sans transaction, les versions restent : la relance repart du même checkpoint.
    assert len(clickhouse.inserted) == 86
    assert clickhouse.checkpoints == []


def test_all_reviews_newer_than_the_checkpoint_close_it(slept: list[float]) -> None:
    """Seule review du jeu éditée : le checkpoint n'est jamais rejoint, le total suffit."""
    steam = FakeSteam(reviews(1), total_reviews=1)
    clickhouse = FakeClickHouse()

    result = sync_app_reviews(
        steam,
        clickhouse,
        app_id=3544130,
        last_seen_timestamp_updated=1_600_000_000,
    )

    assert result.reached_checkpoint
    assert slept == []
    assert clickhouse.checkpoints


class FakeSteamTerminalPage:
    """Sert la même page non vide sans curseur : la réponse est finale d'emblée."""

    def __init__(self, reviews: list[dict[str, Any]], total_reviews: int) -> None:
        self.reviews = reviews
        self.total_reviews = total_reviews
        self.calls: list[str] = []

    def get_all_reviews(self, app_id: int, *, cursor: str, language: str) -> dict:
        self.calls.append(cursor)
        return {
            "reviews": self.reviews,
            "cursor": None,
            **summary(self.total_reviews),
        }


def test_stops_on_a_terminal_page_that_still_carries_reviews(
    slept: list[float],
) -> None:
    """Une dernière page sans curseur doit compter, et servir ses reviews."""
    steam = FakeSteamTerminalPage(reviews(86), total_reviews=86)
    pages = NewReviewPages(
        steam, app_id=3544130, last_seen_timestamp_updated=0, total_reviews=86
    )

    served = [review for page in pages for review in page]

    assert len(served) == 86
    assert pages.reached_checkpoint
    assert slept == []
    assert steam.calls == ["*"]


def test_does_not_accumulate_the_same_page_across_retries(slept: list[float]) -> None:
    """Rejouer un curseur ne rapproche pas du total recensé : 100 reviews sur 700."""
    steam = FakeSteamTerminalPage(reviews(100), total_reviews=700)
    pages = NewReviewPages(
        steam, app_id=3544130, last_seen_timestamp_updated=0, total_reviews=700
    )

    list(pages)

    assert slept == [5.0, 10.0, 20.0, 40.0, 80.0, 160.0]
