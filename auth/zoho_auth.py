"""
Zoho Books OAuth2 token manager.

Uses a persistent refresh token to obtain short-lived access tokens (1 hour).
Caches the access token in memory and auto-refreshes before expiry.

Limits:
- Max 10 access tokens per refresh token per 10 minutes
- Access tokens expire after 3600 seconds
- Max 20 refresh tokens per user
"""

import logging
import threading
import time

import requests

logger = logging.getLogger(__name__)

REFRESH_MARGIN_SECONDS = 300  # refresh 5 min before expiry


class ZohoAuth:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        accounts_url: str = "https://accounts.zoho.com",
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.accounts_url = accounts_url.rstrip("/")
        self._access_token: str = ""
        self._expires_at: float = 0.0
        self._lock = threading.Lock()

    def get_access_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        with self._lock:
            if self._access_token and time.time() < (
                self._expires_at - REFRESH_MARGIN_SECONDS
            ):
                return self._access_token
            return self._refresh()

    def _refresh(self) -> str:
        """Exchange refresh_token for a new access_token."""
        url = f"{self.accounts_url}/oauth/v2/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }
        resp = requests.post(url, data=data, timeout=30)
        resp.raise_for_status()
        body = resp.json()

        if "error" in body:
            raise RuntimeError(f"Zoho token refresh failed: {body['error']}")

        self._access_token = body["access_token"]
        self._expires_at = time.time() + body.get("expires_in", 3600)
        logger.info("Zoho access token refreshed, expires in %ds", body.get("expires_in", 3600))
        return self._access_token

    def get_auth_header(self) -> dict:
        """Return the Authorization header dict."""
        token = self.get_access_token()
        return {"Authorization": f"Zoho-oauthtoken {token}"}
