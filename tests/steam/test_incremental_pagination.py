"""Arrêt de la pagination incrémentale d'un jeu sans checkpoint.

Le budget de relances existe pour survivre aux faux signaux de fin de Steam.
Sans checkpoint à rejoindre, seul le total recensé peut dire si la fin annoncée
est vraie : ces tests vérifient qu'on ne dort pas quand elle l'est, et qu'on
relance toujours quand elle ne l'est pas.
"""

from typing import Any

import pytest

from contextlib import contextmanager

from orchestration.steam import incremental
from orchestration.steam.incremental import NewReviewPages, sync_app_reviews

PAGE_CURSOR = "page2"


class FakeSteam:
    """Sert une page de reviews, puis la fin de pagination annoncée par Steam."""

    def __init__(self, reviews: list[dict[str, Any]]) -> None:
        self.reviews = reviews
        self.calls: list[str] = []

    def get_all_reviews(self, app_id: int, *, cursor: str, language: str) -> dict:
        self.calls.append(cursor)
        if cursor == "*":
            return {"reviews": self.reviews, "cursor": PAGE_CURSOR}
        return {"reviews": [], "cursor": None}


@pytest.fixture
def slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Capture les attentes du backoff au lieu de les subir."""
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
    steam = FakeSteam(reviews(86))
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
    steam = FakeSteam(reviews(86))
    pages = NewReviewPages(
        steam, app_id=3544130, last_seen_timestamp_updated=0, total_reviews=1000
    )

    list(pages)

    assert slept == [5.0, 10.0, 20.0, 40.0, 80.0, 160.0]


class FakeCursor:
    def __init__(self, conn: "FakeConn") -> None:
        self.conn = conn

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def execute(self, sql: str, params: tuple) -> None:
        self.conn.checkpoints.append(params)

    def executemany(self, sql: str, rows: list[tuple]) -> None:
        self.conn.inserted.extend(rows)


class FakeConn:
    def __init__(self) -> None:
        self.inserted: list[tuple] = []
        self.checkpoints: list[tuple] = []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


class FakePostgres:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    @contextmanager
    def connect(self):
        yield self.conn


def test_sync_hands_the_census_total_to_the_paginator(slept: list[float]) -> None:
    """Le total recensé doit descendre jusqu'au paginateur, sinon rien ne change."""
    steam = FakeSteam(reviews(86))
    conn = FakeConn()

    result = sync_app_reviews(
        steam,
        FakePostgres(conn),
        app_id=3544130,
        last_seen_timestamp_updated=0,
        total_reviews=86,
    )

    assert result.reached_checkpoint
    assert len(conn.inserted) == 86
    assert slept == []
