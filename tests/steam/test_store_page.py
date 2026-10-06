"""Fiche store supprimée : seule une redirection vers l'accueil compte, sans réseau."""

import httpx
import pytest

from tests.steam.test_throttle import steam_with_transport

HOME = "https://store.steampowered.com/"


@pytest.mark.parametrize(
    ("response", "removed"),
    [
        (httpx.Response(302, headers={"location": HOME}), True),
        (httpx.Response(200), False),
        (httpx.Response(302, headers={"location": f"{HOME}agecheck/app/10/"}), False),
        (httpx.Response(503), False),
    ],
)
def test_only_a_redirect_to_the_store_home_means_removed(
    response: httpx.Response, removed: bool
) -> None:
    steam = steam_with_transport(lambda request: response)

    assert steam.is_removed_from_store(10) is removed
