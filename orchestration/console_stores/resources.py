"""Notes des joueurs du PS Store et du Microsoft Store."""

import json
import re
import time
from typing import Any

import httpx
from dagster import ConfigurableResource, InitResourceContext
from pydantic import PrivateAttr
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

WIDGET_DATA = re.compile(
    r'<script id="env:[^"]+" type="application/json">(.*?)</script>', re.DOTALL
)


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


transient_retry = retry(
    retry=retry_if_exception(_is_transient),
    wait=wait_exponential(multiplier=2, max=120),
    stop=stop_after_attempt(6),
    reraise=True,
)


def playstation_rating_from_page(
    html: str, concept_id: str
) -> tuple[float, int, list[str]] | None:
    """Note et plateformes du produit par défaut du concept, lues dans le cache Apollo des widgets."""
    rating = None
    platforms: list[str] = []
    for match in WIDGET_DATA.finditer(html):
        cache: dict[str, Any] = json.loads(match.group(1)).get("cache", {})
        concept = cache.get(f"Concept:{concept_id}") or {}
        product = cache.get((concept.get("defaultProduct") or {}).get("__ref")) or {}
        star_rating = product.get("starRating") or {}
        if star_rating.get("totalRatingsCount"):
            rating = (star_rating["averageRating"], star_rating["totalRatingsCount"])
        platforms = platforms or product.get("platforms") or []
    return (*rating, platforms) if rating else None


def xbox_platforms(product: dict[str, Any]) -> list[str]:
    console_gens = {"ConsoleGen8": "Xbox One", "ConsoleGen9": "Xbox Series X|S"}
    platforms = [
        console_gens[gen]
        for gen in (product.get("Properties") or {}).get("XboxConsoleGenCompatible")
        or []
        if gen in console_gens
    ]
    if any(
        dependency.get("PlatformName") == "Windows.Desktop"
        for availability in product.get("DisplaySkuAvailabilities", [])
        for package in availability["Sku"]["Properties"].get("Packages") or []
        for dependency in package.get("PlatformDependencies") or []
    ):
        platforms.append("PC")
    return platforms


def xbox_ratings_from_catalog(
    payload: dict[str, Any],
) -> dict[str, tuple[float, int, list[str]]]:
    ratings = {}
    for product in payload.get("Products", []):
        for market in product.get("MarketProperties", []):
            for usage in market.get("UsageData", []):
                if usage.get("AggregateTimeSpan") == "AllTime" and usage.get(
                    "RatingCount"
                ):
                    ratings[product["ProductId"]] = (
                        usage["AverageRating"],
                        usage["RatingCount"],
                        xbox_platforms(product),
                    )
    return ratings


class ConsoleStoreResource(ConfigurableResource):
    playstation_min_interval_seconds: float = 1.0
    request_timeout_seconds: float = 30.0

    _client: httpx.Client = PrivateAttr()
    _next_playstation_ts: float = PrivateAttr(default=0.0)

    def setup_for_execution(self, context: InitResourceContext) -> None:
        self._client = httpx.Client(
            timeout=self.request_timeout_seconds,
            headers={"User-Agent": "Mozilla/5.0"},
        )

    @transient_retry
    def get_playstation_rating(
        self, concept_id: str
    ) -> tuple[float, int, list[str]] | None:
        wait = self._next_playstation_ts - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._next_playstation_ts = (
            time.monotonic() + self.playstation_min_interval_seconds
        )
        resp = self._client.get(
            f"https://store.playstation.com/en-us/concept/{concept_id}"
        )
        # Concept retiré : redirection vers une page d'erreur.
        if resp.is_redirect:
            return None
        resp.raise_for_status()
        return playstation_rating_from_page(resp.text, concept_id)

    @transient_retry
    def get_xbox_ratings(
        self, product_ids: list[str]
    ) -> dict[str, tuple[float, int, list[str]]]:
        resp = self._client.get(
            "https://displaycatalog.mp.microsoft.com/v7.0/products",
            params={
                "bigIds": ",".join(product_ids),
                "market": "US",
                "languages": "en-us",
            },
        )
        resp.raise_for_status()
        return xbox_ratings_from_catalog(resp.json())
