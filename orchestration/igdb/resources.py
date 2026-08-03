"""Client IGDB (auth OAuth via Twitch client credentials)."""

import time
from pathlib import Path

import httpx
from dagster import ConfigurableResource, get_dagster_logger
from pydantic import PrivateAttr

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
API_BASE_URL = "https://api.igdb.com/v4"


class IGDBResource(ConfigurableResource):
    """Accès à l'API IGDB."""

    client_id: str
    client_secret: str
    request_timeout_seconds: float = 20.0
    dump_download_timeout_seconds: float = 600.0

    _access_token: str | None = PrivateAttr(default=None)
    _token_expires_at: float = PrivateAttr(default=0.0)

    def _ensure_token(self) -> str:
        # Marge de 60s pour ne pas utiliser un token qui expire à l'instant.
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        logger = get_dagster_logger()
        logger.info("IGDB : récupération d'un token Twitch (client_credentials)")
        resp = httpx.post(
            TOKEN_URL,
            params={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
            timeout=self.request_timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        return self._access_token

    def _headers(self) -> dict[str, str]:
        return {
            "Client-ID": self.client_id,
            "Authorization": f"Bearer {self._ensure_token()}",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    # Data dumps (https://api-docs.igdb.com/#dumps)
    # ------------------------------------------------------------------
    def get_dump_url(self, endpoint: str) -> str:
        """Obtient l'URL S3 (signée, éphémère) de téléchargement d'un dump."""
        resp = httpx.get(
            f"{API_BASE_URL}/dumps/{endpoint}",
            headers=self._headers(),
            timeout=self.request_timeout_seconds,
        )
        resp.raise_for_status()
        s3_url = resp.json().get("s3_url")
        if not s3_url:
            raise ValueError(f"IGDB : pas de s3_url pour le dump '{endpoint}'")
        return s3_url

    def download_dump(self, endpoint: str, dest_dir: Path) -> Path:
        """Télécharge le dump CSV d'un endpoint dans `dest_dir`, renvoie le chemin."""
        logger = get_dagster_logger()
        s3_url = self.get_dump_url(endpoint)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / f"{endpoint}.csv"

        logger.info(f"IGDB : téléchargement du dump '{endpoint}'…")
        with httpx.stream(
            "GET", s3_url, timeout=self.dump_download_timeout_seconds
        ) as resp:
            resp.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=1 << 20):
                    f.write(chunk)

        logger.info(f"IGDB : dump '{endpoint}' téléchargé → {dest_path}")
        return dest_path
