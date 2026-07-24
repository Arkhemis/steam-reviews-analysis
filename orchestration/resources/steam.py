"""Client HTTP centralisé pour l'API reviews de Steam.

Endpoint : https://store.steampowered.com/appreviews/{app_id}?json=1
"""

import threading
import time
from typing import Any

import httpx
from dagster import ConfigurableResource, get_dagster_logger
from pydantic import PrivateAttr

BASE_URL = "https://store.steampowered.com/appreviews"


class SteamResource(ConfigurableResource):
    """Client Steam reviews avec rate limit + retries."""

    min_interval_seconds: float = 0.1
    # Backoff exponentiel sur 429 / timeout / 5xx.
    max_retries: int = 5
    backoff_base_seconds: float = 2.0
    request_timeout_seconds: float = 20.0

    _client: httpx.Client = PrivateAttr()
    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)
    _next_slot_ts: float = PrivateAttr(default=0.0)

    def setup_for_execution(self, context) -> None:  # noqa: ANN001
        self._client = httpx.Client(timeout=self.request_timeout_seconds)

    def teardown_after_execution(self, context) -> None:  # noqa: ANN001
        self._client.close()

    def _throttle(self) -> None:
        """Réserve le prochain créneau disponible (thread-safe)."""
        with self._lock:
            now = time.monotonic()
            start_at = max(now, self._next_slot_ts)
            self._next_slot_ts = start_at + self.min_interval_seconds
        wait = start_at - now
        if wait > 0:
            time.sleep(wait)

    def _get(self, app_id: int, params: dict[str, Any]) -> dict[str, Any]:
        """Requête GET avec throttle + backoff exponentiel."""
        logger = get_dagster_logger()
        url = f"{BASE_URL}/{app_id}"
        attempt = 0
        while True:
            self._throttle()
            try:
                # httpx URL-encode les query params (dont le cursor) automatiquement.
                resp = self._client.get(url, params=params)
                if resp.status_code == 429:
                    raise httpx.HTTPStatusError(
                        "429 Too Many Requests", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                return resp.json()
            except (httpx.TransportError, httpx.HTTPStatusError, ValueError) as exc:
                attempt += 1
                if attempt > self.max_retries:
                    logger.error(
                        f"app_id={app_id}: abandon après {self.max_retries} retries ({exc})"
                    )
                    raise
                delay = self.backoff_base_seconds**attempt
                logger.warning(
                    f"app_id={app_id}: erreur ({exc}); retry {attempt}/{self.max_retries} dans {delay:.0f}s"
                )
                time.sleep(delay)

    def review_summary(self, app_id: int) -> dict[str, Any]:
        """Sonde de recensement : renvoie `query_summary` seul."""
        data = self._get(
            app_id,
            {
                "json": 1,
                "num_per_page": 0,
                "language": "all",
                "purchase_type": "all",
                "filter": "all",
            },
        )
        return data.get("query_summary", {})
