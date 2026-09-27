"""Client HTTP centralisé pour les API Steam.

Endpoints :
- reviews   : https://store.steampowered.com/appreviews/{app_id}
- annonces  : https://store.steampowered.com/events/ajaxgetpartnereventspageable/
- fiches    : https://api.steampowered.com/IStoreBrowseService/GetItems/v1/

Depuis le 24/09, /appreviews a sa propre limite par IP (réserve de ~270
requêtes rechargée à ~0,96/s, blocage de ~4 min 30) : il a son propre throttle,
plus lent et adaptatif. GetItems a une limite distincte (réserve de ~125 lots,
~0,78 lot/s soutenu) dont le 429 ne bloque pas l'IP : quelques secondes suffisent.
Les annonces gardent le throttle rapide.
"""

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from dagster import ConfigurableResource, InitResourceContext, get_dagster_logger
from pydantic import PrivateAttr

BASE_URL = "https://store.steampowered.com"
# Endpoint non documenté, sans clé ; au-delà de ~250 ids l'URL devient trop longue (400).
STORE_ITEMS_URL = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/"

# Après autant de succès d'affilée, l'intervalle /appreviews redescend de 5 %.
REVIEWS_SPEEDUP_AFTER = 500
REVIEWS_SPEEDUP_FACTOR = 0.95
REVIEWS_SLOWDOWN_FACTOR = 1.5

Lane = Literal["default", "items", "reviews"]


@dataclass
class _LaneState:
    """Créneaux d'un endpoint : partagés par tous les threads de la resource."""

    interval: float
    next_slot_ts: float = 0.0
    paused_until: float = 0.0
    ok_streak: int = 0


class SteamApiError(Exception):
    """Erreur permanente de l'API Steam (4xx hors 429, ou `success` != 1).

    Elle échappe volontairement au `except` de `_get` : retenter un appid sans
    hub d'annonces coûterait 254 s de backoff pour un échec certain.
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
    """Client Steam (reviews, annonces, fiches store) avec rate limit + retries."""

    min_interval_seconds: float = 0.1
    # Plancher /appreviews : 0,8 req/s, sous la recharge mesurée (~0,96/s).
    reviews_min_interval_seconds: float = 1.25
    reviews_max_interval_seconds: float = 5.0
    # Couvre le blocage mesuré (~4 min 30) d'une seule attente.
    rate_limit_pause_seconds: float = 300.0
    # GetItems : 1,3 s entre deux lots tient le débit soutenu mesuré (~0,78/s).
    items_min_interval_seconds: float = 1.3
    # Son 429 n'est qu'une réserve vide : un lot rejoué 1 s après passe.
    items_rate_limit_pause_seconds: float = 5.0
    # Sur 429, chaque retry coûte une pause entière, pas le backoff.
    max_retries: int = 7
    # Backoff exponentiel sur 429 / timeout / 5xx.
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
            "reviews": _LaneState(self.reviews_min_interval_seconds),
        }

    def _throttle(self, lane: Lane) -> None:
        """Réserve le prochain créneau disponible de l'endpoint (thread-safe)."""
        with self._lock:
            state = self._lanes[lane]
            now = time.monotonic()
            start_at = max(now, state.next_slot_ts)
            state.next_slot_ts = start_at + state.interval
        wait = start_at - now
        if wait > 0:
            time.sleep(wait)

    def _on_success(self, lane: Lane) -> None:
        if lane != "reviews":
            return
        with self._lock:
            state = self._lanes[lane]
            state.ok_streak += 1
            if (
                state.ok_streak >= REVIEWS_SPEEDUP_AFTER
                and state.interval > self.reviews_min_interval_seconds
            ):
                state.interval = max(
                    self.reviews_min_interval_seconds,
                    state.interval * REVIEWS_SPEEDUP_FACTOR,
                )
                state.ok_streak = 0

    def _on_rate_limited(self, lane: Lane, app_id: int) -> None:
        """Le 429 vaut pour toute l'IP : on gèle l'endpoint pour tous les threads."""
        pause = (
            self.items_rate_limit_pause_seconds
            if lane == "items"
            else self.rate_limit_pause_seconds
        )
        with self._lock:
            state = self._lanes[lane]
            now = time.monotonic()
            state.ok_streak = 0
            # Les requêtes déjà en vol pendant la pause ne ralentissent pas une 2e fois.
            if now < state.paused_until:
                return
            state.paused_until = now + pause
            state.next_slot_ts = max(state.next_slot_ts, state.paused_until)
            if lane == "reviews":
                state.interval = min(
                    self.reviews_max_interval_seconds,
                    state.interval * REVIEWS_SLOWDOWN_FACTOR,
                )
            interval = state.interval
        get_dagster_logger().warning(
            f"app_id={app_id}: 429 sur {lane}, pause de "
            f"{pause:.0f}s puis une requête toutes les {interval:.2f}s"
        )

    def reviews_interval_seconds(self) -> float:
        """Intervalle /appreviews atteint, pour les métadonnées des assets."""
        with self._lock:
            return self._lanes["reviews"].interval

    def _get(
        self,
        url: str,
        params: dict[str, Any],
        *,
        app_id: int,
        lane: Lane = "default",
    ) -> dict[str, Any]:
        """Requête GET avec throttle + backoff exponentiel (`app_id` sert aux logs)."""
        logger = get_dagster_logger()
        attempt = 0
        while True:
            self._throttle(lane)
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
                data = resp.json()
                self._on_success(lane)
                return data
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

    def get_summary(self, app_id: int, language: str = "all") -> dict[str, Any]:
        """Recensement : renvoie la réponse entière, dont `query_summary` (total_reviews, review_score, ...)."""
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
            lane="reviews",
        )
        return data

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
            lane="reviews",
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

    def get_store_items(
        self,
        app_ids: list[int],
        country_code: str = "US",
        *,
        include_release: bool = True,
        include_reviews: bool = False,
    ) -> list[dict[str, Any]]:
        """Fiches store d'un lot d'apps (type, DLC parent, early access, dates, reviews)."""
        data = self._get(
            STORE_ITEMS_URL,
            {
                "input_json": json.dumps(
                    {
                        "ids": [{"appid": app_id} for app_id in app_ids],
                        "context": {"country_code": country_code},
                        "data_request": {
                            "include_release": include_release,
                            "include_reviews": include_reviews,
                        },
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
