"""
Low-level Zoho Books API client.

Handles authentication, rate limiting (100 req/min), and retries.
All service modules use this client.
"""

import logging
import threading
import time

import requests as req

from auth.zoho_auth import ZohoAuth

logger = logging.getLogger(__name__)


class ZohoClient:
    """HTTP client for Zoho Books API v3."""

    RATE_LIMIT_INTERVAL = 0.65  # ~92 req/min, safely under 100

    def __init__(self, auth: ZohoAuth, base_url: str, organization_id: str):
        self.auth = auth
        self.base_url = base_url.rstrip("/")
        self.organization_id = organization_id
        self._last_request_time = 0.0
        self._rate_lock = threading.Lock()

    def _wait_for_rate_limit(self):
        with self._rate_lock:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.RATE_LIMIT_INTERVAL:
                time.sleep(self.RATE_LIMIT_INTERVAL - elapsed)
            self._last_request_time = time.time()

    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        """Authenticated API request with rate limiting and retries."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        params = kwargs.pop("params", {})
        params["organization_id"] = self.organization_id

        for attempt in range(3):
            self._wait_for_rate_limit()
            headers = self.auth.get_auth_header()
            headers["Content-Type"] = "application/json"

            resp = req.request(
                method, url, headers=headers, params=params, **kwargs
            )

            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 60))
                logger.warning("Rate limited. Waiting %ds...", wait)
                time.sleep(wait)
                continue

            if resp.status_code == 401 and attempt == 0:
                logger.warning("401 — forcing token refresh")
                self.auth._refresh()
                continue

            if not resp.ok:
                logger.error(f"HTTP {resp.status_code}: {resp.text}")
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                msg = data.get("message", "Unknown Zoho API error")
                raise RuntimeError(f"Zoho API error: {msg} (code {data.get('code')})")

            return data

        raise RuntimeError(f"API request failed after 3 attempts: {method} {endpoint}")

    def get(self, endpoint: str, **kwargs) -> dict:
        return self._request("GET", endpoint, **kwargs)

    def post(self, endpoint: str, **kwargs) -> dict:
        return self._request("POST", endpoint, **kwargs)

    def put(self, endpoint: str, **kwargs) -> dict:
        return self._request("PUT", endpoint, **kwargs)

    def delete(self, endpoint: str, **kwargs) -> dict:
        return self._request("DELETE", endpoint, **kwargs)
