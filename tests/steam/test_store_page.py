"""Fiche store supprimée : seule une redirection vers l'accueil compte, sans réseau."""

import httpx
import pytest

from tests.steam.conftest import FakeClock
from tests.steam.test_throttle import steam_with_transport

HOME = "https://store.steampowered.com/"


@pytest.mark.parametrize(
    ("response", "removed"),
    [
        (httpx.Response(302, headers={"location": HOME}), True),
        (httpx.Response(200), False),
        (httpx.Response(302, headers={"location": f"{HOME}agecheck/app/10/"}), False),
    ],
)
def test_only_a_redirect_to_the_store_home_means_removed(
    clock: FakeClock, response: httpx.Response, removed: bool
) -> None:
    steam = steam_with_transport(lambda request: response)

    assert steam.is_removed_from_store(10) is removed


def test_429_pauses_the_lane_then_checks_again(clock: FakeClock) -> None:
    responses = iter([429, 302])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(responses), headers={"location": HOME})

    steam = steam_with_transport(handler)
    start = clock.now

    assert steam.is_removed_from_store(10) is True
    assert clock.now - start >= steam.rate_limit_pause_seconds


def test_server_error_is_a_failure_not_a_live_page(clock: FakeClock) -> None:
    steam = steam_with_transport(lambda request: httpx.Response(503))

    with pytest.raises(httpx.HTTPStatusError):
        steam.is_removed_from_store(10)
