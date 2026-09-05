"""Client HTTP centralisé pour les API Steam.

Endpoints :
- reviews   : https://store.steampowered.com/appreviews/{app_id}
- annonces  : https://store.steampowered.com/events/ajaxgetpartnereventspageable/

Les deux tapent le même host, donc le même budget de rate limit : ils doivent
partager cette resource, et donc son throttle.
"""

import threading
import time
from typing import Any

import httpx
from dagster import ConfigurableResource, InitResourceContext, get_dagster_logger
from pydantic import PrivateAttr

BASE_URL = "https://store.steampowered.com"


class SteamApiError(Exception):
    """Erreur permanente de l'API Steam (4xx hors 429, ou `success` != 1).

    Elle échappe volontairement au `except` de `_get` : retenter un appid sans
    hub d'annonces coûterait 62 s de backoff pour un échec certain.
    """

    def __init__(self, app_id: int, success: Any, err_msg: str) -> None:
        super().__init__(f"app_id={app_id}: success={success} ({err_msg})")
        self.app_id = app_id
        self.success = success
        self.err_msg = err_msg

    @classmethod
    def from_response(cls, app_id: int, resp: httpx.Response) -> "SteamApiError":
        """Steam décrit ses refus dans le corps du 4xx : `success` 42 = pas de
        hub d'annonces pour cet appid, 8 = paramètres incomplets."""
        try:
            body = resp.json()
        except ValueError:
            body = {}
        return cls(
            app_id,
            body.get("success", f"HTTP {resp.status_code}"),
            body.get("err_msg", resp.reason_phrase),
        )


class SteamResource(ConfigurableResource):
    """Client Steam (reviews + annonces) avec rate limit + retries."""

    min_interval_seconds: float = 0.1
    max_retries: int = 5
    # Backoff exponentiel sur 429 / timeout / 5xx.
    backoff_base_seconds: float = 2.0
    request_timeout_seconds: float = 20.0

    _client: httpx.Client = PrivateAttr()
    _lock: threading.Lock = PrivateAttr()
    _next_slot_ts: float = PrivateAttr(default=0.0)

    def setup_for_execution(self, context: InitResourceContext) -> None:
        self._client = httpx.Client(timeout=self.request_timeout_seconds)
        self._lock = threading.Lock()

    def _throttle(self) -> None:
        """Réserve le prochain créneau disponible (thread-safe)."""
        with self._lock:
            now = time.monotonic()
            start_at = max(now, self._next_slot_ts)
            self._next_slot_ts = start_at + self.min_interval_seconds
        wait = start_at - now
        if wait > 0:
            time.sleep(wait)

    def _get(self, url: str, params: dict[str, Any], *, app_id: int) -> dict[str, Any]:
        """Requête GET avec throttle + backoff exponentiel (`app_id` sert aux logs)."""
        logger = get_dagster_logger()
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
                if 400 <= resp.status_code < 500:
                    raise SteamApiError.from_response(app_id, resp)
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

    def get_summary(self, app_id: int, language: str = "all") -> dict[str, Any]:
        """Recensement : renvoie `query_summary` (total_reviews, review_score, ...) pour un jeu."""
        data = self._get(
            f"{BASE_URL}/appreviews/{app_id}",
            {
                "json": 1,
                "num_per_page": 0,
                "language": language,
                "purchase_type": "all",
                "filter": "all",
                "filter_offtopic_activity": 0,  # inclus le review bombing (aligné avec get_all_reviews)
            },
            app_id=app_id,
        )
        return data.get("query_summary", {})

    def get_all_reviews(
        self,
        app_id: int,
        num_per_page: int = 100,
        language: str = "all",
        cursor: str = "*",
    ) -> dict[str, Any]:
        """Renvoie les reviews Steam."""
        return self._get(
            f"{BASE_URL}/appreviews/{app_id}",
            {
                "json": 1,
                "num_per_page": num_per_page,
                "language": language,
                "purchase_type": "all",
                "filter": "updated",  # ordonné par date de mise à jour ; "recent" tronque le curseur au-delà de ~120k reviews (bug Steam connu)
                "filter_offtopic_activity": 0,  # inclus le review bombing
                "cursor": cursor,
            },
            app_id=app_id,
        )

    def get_events(
        self,
        app_id: int,
        count: int = 100,
        offset: int = 0,
        language: str = "english",
    ) -> dict[str, Any]:
        """Renvoie une page d'annonces du jeu (patch notes, MAJ, actus)."""
        data = self._get(
            f"{BASE_URL}/events/ajaxgetpartnereventspageable/",
            # Contrairement à appreviews, l'app_id est un query param.
            {
                "appid": app_id,
                "offset": offset,
                "count": count,
                "l": language,
            },
            app_id=app_id,
        )
        if data.get("success") != 1:
            raise SteamApiError(app_id, data.get("success"), data.get("err_msg", ""))
        return data
