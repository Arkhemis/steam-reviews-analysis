"""Fiches store : requête envoyée à GetItems et lecture de sa réponse, sans réseau."""

import json

import httpx
import pytest

from orchestration.steam.resources import SteamApiError, SteamResource


def steam_with_transport(handler) -> SteamResource:
    steam = SteamResource(min_interval_seconds=0)
    steam.setup_for_execution(None)
    steam._client = httpx.Client(transport=httpx.MockTransport(handler))
    return steam


def test_get_store_items_sends_every_id_with_a_country():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.url.params["input_json"]))
        return httpx.Response(200, json={"response": {"store_items": [{"id": 730}]}})

    items = steam_with_transport(handler).get_store_items([730, 570])

    assert items == [{"id": 730}]
    assert requests[0]["ids"] == [{"appid": 730}, {"appid": 570}]
    # Sans country_code, Steam renvoie une réponse vide.
    assert requests[0]["context"]["country_code"] == "US"


def test_get_store_items_rejects_an_empty_response_without_retrying():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"response": {}})

    with pytest.raises(SteamApiError):
        steam_with_transport(handler).get_store_items([730])
    assert len(calls) == 1
