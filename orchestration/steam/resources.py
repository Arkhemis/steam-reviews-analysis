"""Client HTTP des API Steam, un throttle par endpoint."""

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from dagster import ConfigurableResource, InitResourceContext, get_dagster_logger
from pydantic import PrivateAttr

# Au-delà de ~250 ids, l'URL est trop longue (400).
STORE_ITEMS_URL = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/"
STORE_HOME_URL = "https://store.steampowered.com/"

Lane = Literal["default", "items", "reviews"]


@dataclass
class _LaneState:
    interval: float
    next_slot_ts: float = 0.0
    paused_until: float = 0.0


class SteamApiError(Exception):
    """Erreur permanente (4xx hors 429, ou `success` != 1), jamais retentée."""

    def __init__(self, app_id: int, success: Any, err_msg: str) -> None:
        super().__init__(f"app_id={app_id}: success={success} ({err_msg})")
        self.app_id = app_id
        self.success = success
        self.err_msg = err_msg

    @classmethod
    def from_response(cls, app_id: int, resp: httpx.Response) -> "SteamApiError":
        # `success` 42 : pas de hub d'annonces ; 8 : paramètres incomplets.
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
    min_interval_seconds: float = 0.1
    rate_limit_pause_seconds: float = 300.0
    items_min_interval_seconds: float = 1.3
    # Le 429 de GetItems ne bloque pas l'IP.
    items_rate_limit_pause_seconds: float = 5.0
    max_retries: int = 7
    backoff_base_seconds: float = 2.0
    request_timeout_seconds: float = 20.0

    _client: httpx.Client = PrivateAttr()
    _lock: threading.Lock = PrivateAttr()
    _lanes: dict[str, _LaneState] = PrivateAttr()

    def setup_for_execution(self, context: InitResourceContext) -> None:
        self._client = httpx.Client(timeout=self.request_timeout_seconds)
        self._lock = threading.Lock()
        self._lanes = {
            "default": _LaneState(self.min_interval_seconds),
            "items": _LaneState(self.items_min_interval_seconds),
            "reviews": _LaneState(self.min_interval_seconds),
        }

    def _throttle(self, lane: Lane) -> None:
        while True:
            with self._lock:
                state = self._lanes[lane]
                now = time.monotonic()
                start_at = max(now, state.next_slot_ts)
                state.next_slot_ts = start_at + state.interval
            wait = start_at - now
            if wait > 0:
                time.sleep(wait)
            # Un 429 a pu tomber pendant l'attente.
            with self._lock:
                if time.monotonic() >= self._lanes[lane].paused_until:
                    return

    def _on_rate_limited(self, lane: Lane, app_id: int) -> None:
        # Le 429 vaut pour toute l'IP : l'endpoint gèle pour tous les threads.
        pause = (
            self.items_rate_limit_pause_seconds
            if lane == "items"
            else self.rate_limit_pause_seconds
        )
        with self._lock:
            state = self._lanes[lane]
            now = time.monotonic()
            # Les requêtes en vol ne relancent pas la pause.
            if now < state.paused_until:
                return
            state.paused_until = now + pause
            state.next_slot_ts = max(state.next_slot_ts, state.paused_until)
        get_dagster_logger().warning(
            f"app_id={app_id}: 429 sur {lane}, pause de {pause:.0f}s"
        )

    def _get(
        self,
        url: str,
        params: dict[str, Any],
        *,
        app_id: int,
        lane: Lane = "default",
    ) -> dict[str, Any]:
        logger = get_dagster_logger()
        attempt = 0
        while True:
            self._throttle(lane)
            try:
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
                if (
                    isinstance(exc, httpx.HTTPStatusError)
                    and exc.response.status_code == 429
                ):
                    # Pas de sleep ici : le prochain créneau tombe après la pause.
                    self._on_rate_limited(lane, app_id)
                    continue
                delay = self.backoff_base_seconds**attempt
                logger.warning(
                    f"app_id={app_id}: erreur ({exc}); retry {attempt}/{self.max_retries} dans {delay:.0f}s"
                )
                time.sleep(delay)

    def get_all_reviews(
        self,
        app_id: int,
        num_per_page: int = 100,
        language: str = "all",
        cursor: str = "*",
    ) -> dict[str, Any]:
        data = self._get(
            "https://api.steampowered.com/IUserReviewsService/GetAppReviews/v1/",
            {
                "appid": app_id,
                "num_per_page": num_per_page,
                "languages[0]": language,
                "purchase_type": 1,  # toutes
                "filter": 2,  # updated
                "filter_offtopic_activity": False,  # inclut le review bombing
                "cursor": cursor,
            },
            app_id=app_id,
            lane="reviews",
        )
        return data.get("response", {})

    def is_removed_from_store(self, app_id: int) -> bool:
        """Fiche supprimée : la page redirige vers l'accueil (bloquée dans le pays, elle reste en 200)."""
        self._throttle("default")
        resp = self._client.get(f"{STORE_HOME_URL}app/{app_id}/")
        return resp.is_redirect and resp.headers.get("location") == STORE_HOME_URL

    def get_events(
        self,
        app_id: int,
        count: int = 100,
        offset: int = 0,
        language: str = "english",
    ) -> dict[str, Any]:
        data = self._get(
            "https://store.steampowered.com/events/ajaxgetpartnereventspageable/",
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

    def get_store_items(
        self,
        app_ids: list[int],
        country_code: str = "US",
    ) -> list[dict[str, Any]]:
        data = self._get(
            STORE_ITEMS_URL,
            {
                "input_json": json.dumps(
                    {
                        "ids": [{"appid": app_id} for app_id in app_ids],
                        "context": {"country_code": country_code},
                        "data_request": {"include_release": True},
                    }
                )
            },
            app_id=app_ids[0],
            lane="items",
        )
        items = data.get("response", {}).get("store_items")
        if items is None:
            raise SteamApiError(app_ids[0], "HTTP 200", "réponse sans store_items")
        return items
