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


def test_reviews_pause_after_their_quota(clock):
    steam = steam_with_transport(ok)
    start = clock.now
    for _ in range(150):
        steam.get_summary(730)
    # 150 créneaux à 0,1 s : le dernier part 149 × 0,1 s après le premier.
    assert clock.now - start == pytest.approx(14.9)

    steam.get_summary(730)
    # Le 151e attend 310 s après le 150e.
    assert clock.now - start == pytest.approx(14.9 + 310)


def test_other_endpoints_keep_the_fast_interval(clock):
    steam = steam_with_transport(ok)
    start = clock.now
    for _ in range(3):
        steam.get_events(730)
    assert clock.now - start == pytest.approx(0.2)


def test_429_pauses_reviews_and_restores_the_quota(clock):
    responses = iter([429, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(responses), json={"success": 1})

    steam = steam_with_transport(handler)
    start = clock.now
    steam.get_summary(730)

    assert clock.now - start == pytest.approx(300)
    assert steam._lanes["reviews"].used == 1


def test_429s_in_flight_during_a_pause_do_not_extend_it(clock):
    steam = steam_with_transport(ok)
    steam._on_rate_limited("reviews", 730)
    clock.sleep(100)
    steam._on_rate_limited("reviews", 570)
    assert steam._lanes["reviews"].paused_until == pytest.approx(1300)


def test_429_on_reviews_leaves_other_endpoints_running(clock):
    steam = steam_with_transport(ok)
    steam._on_rate_limited("reviews", 730)
    start = clock.now
    steam.get_events(730)
    assert clock.now - start < 1


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
    assert steam._lanes["reviews"].paused_until == 0.0


def test_429_on_store_items_leaves_reviews_running(clock):
    steam = steam_with_transport(ok)
    steam._on_rate_limited("items", 730)
    start = clock.now
    steam.get_summary(730)
    assert clock.now - start < 1


def test_a_slot_reserved_before_a_429_waits_for_the_pause(clock, monkeypatch):
    steam = steam_with_transport(ok)
    steam._throttle("reviews")
    start = clock.now

    # Un autre thread prend un 429 pendant que celui-ci attend son créneau.
    def sleep_then_429(seconds: float) -> None:
        clock.sleep(seconds)
        if steam._lanes["reviews"].paused_until == 0.0:
            steam._on_rate_limited("reviews", 570)

    monkeypatch.setattr(resources.time, "sleep", sleep_then_429)
    steam._throttle("reviews")
    assert clock.now - start == pytest.approx(0.1 + 300)
