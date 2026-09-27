"""Throttle par endpoint de SteamResource, avec une horloge factice et sans réseau."""

import httpx
import pytest

from orchestration.steam import resources
from orchestration.steam.resources import SteamResource


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(resources.time, "monotonic", fake.monotonic)
    monkeypatch.setattr(resources.time, "sleep", fake.sleep)
    return fake


def steam_with_transport(handler) -> SteamResource:
    steam = SteamResource(min_interval_seconds=0.1)
    steam.setup_for_execution(None)
    steam._client = httpx.Client(transport=httpx.MockTransport(handler))
    return steam


def ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"success": 1, "query_summary": {}})


def test_reviews_are_spaced_by_their_own_interval(clock):
    steam = steam_with_transport(ok)
    start = clock.now
    for _ in range(3):
        steam.get_summary(730)
    # Trois créneaux réservés : le troisième part 2 × 1,25 s après le premier.
    assert clock.now - start == pytest.approx(2.5)


def test_other_endpoints_keep_the_fast_interval(clock):
    steam = steam_with_transport(ok)
    start = clock.now
    for _ in range(3):
        steam.get_events(730)
    assert clock.now - start == pytest.approx(0.2)


def test_429_pauses_reviews_once_and_slows_down(clock):
    responses = iter([429, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(responses), json={"success": 1})

    steam = steam_with_transport(handler)
    start = clock.now
    steam.get_summary(730)

    assert clock.now - start == pytest.approx(300)
    assert steam.reviews_interval_seconds() == pytest.approx(1.875)


def test_429s_in_flight_during_a_pause_slow_down_only_once(clock):
    steam = steam_with_transport(ok)
    steam._on_rate_limited("reviews", 730)
    steam._on_rate_limited("reviews", 570)
    assert steam.reviews_interval_seconds() == pytest.approx(1.875)


def test_429_on_reviews_leaves_other_endpoints_running(clock):
    steam = steam_with_transport(ok)
    steam._on_rate_limited("reviews", 730)
    start = clock.now
    steam.get_events(730)
    assert clock.now - start < 1


def test_reviews_speed_up_after_a_success_streak_but_not_below_the_floor(clock):
    steam = steam_with_transport(ok)
    steam._lanes["reviews"].interval = 1.3
    for _ in range(resources.REVIEWS_SPEEDUP_AFTER):
        steam.get_summary(730)
    assert steam.reviews_interval_seconds() == pytest.approx(1.25)


def test_store_items_have_their_own_interval(clock):
    steam = steam_with_transport(
        lambda request: httpx.Response(200, json={"response": {"store_items": []}})
    )
    start = clock.now
    for _ in range(3):
        steam.get_store_items([730])
    assert clock.now - start == pytest.approx(2.6)


def test_429_on_store_items_pauses_seconds_not_minutes(clock):
    responses = iter([429, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(responses), json={"response": {"store_items": []}})

    steam = steam_with_transport(handler)
    start = clock.now
    steam.get_store_items([730])

    assert clock.now - start == pytest.approx(5)
    assert steam.reviews_interval_seconds() == pytest.approx(1.25)


def test_429_on_store_items_leaves_reviews_running(clock):
    steam = steam_with_transport(ok)
    steam._on_rate_limited("items", 730)
    start = clock.now
    steam.get_summary(730)
    assert clock.now - start < 1
