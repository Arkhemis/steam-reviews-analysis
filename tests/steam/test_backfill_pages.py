"""Fin de pagination du backfill : sans total connu, une page vide peut être une fausse fin."""

import pytest

from orchestration.steam import backfill
from orchestration.steam.backfill import SUMMARY_RETRIES, fetch_steam_reviews
from tests.steam.test_incremental_pagination import FakeSteam, reviews


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backfill.time, "sleep", lambda _: None)


def test_complete_when_page_one_total_is_reached() -> None:
    app_reviews, pages = fetch_steam_reviews(FakeSteam(reviews(86), 86), 1, None)

    assert len(app_reviews) == 86
    assert pages.complete


def test_incomplete_without_any_total() -> None:
    """Page 1 sans query_summary et jeu jamais recensé : rien ne valide la fin."""
    steam = FakeSteam(reviews(86), None)

    app_reviews, pages = fetch_steam_reviews(steam, 1, None)

    assert len(app_reviews) == 86
    assert steam.calls.count("*") == SUMMARY_RETRIES + 1
    assert not pages.complete


def test_incomplete_when_retries_run_out_far_from_total() -> None:
    app_reviews, pages = fetch_steam_reviews(FakeSteam(reviews(86), 5_000), 1, None)

    assert len(app_reviews) == 86
    assert not pages.complete
