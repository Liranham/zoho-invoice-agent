"""
Wise Platform API HTTP client.

Handles personal-token Bearer auth, plus the SCA challenge dance for
"high-risk" endpoints (Statements, Activities). Webhook subscription endpoints
are non-SCA and use Bearer alone.

SCA flow:
    1. We send the request with Bearer.
    2. Wise replies 403 with headers:
         x-2fa-approval-result: REJECTED
         x-2fa-approval: <one-time-token>
    3. We sign the OTT with our RSA private key (via WiseAuth.sign_ott),
       then retry with:
         X-Signature: <base64 sig>
         x-2fa-approval: <same OTT>
    4. Wise returns 200.
"""

from __future__ import annotations

import logging

import requests as req

from wise.auth import WiseAuth

logger = logging.getLogger(__name__)


class WiseClient:
    BASE_URL = "https://api.wise.com"

    def __init__(self, auth: WiseAuth, base_url: str = BASE_URL):
        self.auth = auth
        self.base_url = base_url.rstrip("/")

    # ---- low-level ---------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.base_url}{path}"
        headers = kwargs.pop("headers", {}) or {}
        headers.update(self.auth.auth_header())

        resp = req.request(method, url, headers=headers, timeout=30, **kwargs)

        # SCA challenge?
        if resp.status_code == 403 and resp.headers.get("x-2fa-approval-result") == "REJECTED":
            ott = resp.headers.get("x-2fa-approval")
            if not ott:
                resp.raise_for_status()
            logger.info("Wise SCA challenge for %s %s", method, path)
            signature = self.auth.sign_ott(ott)
            headers["x-2fa-approval"] = ott
            headers["X-Signature"] = signature
            resp = req.request(method, url, headers=headers, timeout=30, **kwargs)

        if not resp.ok:
            logger.error("Wise %s %s -> %d %s", method, path, resp.status_code, resp.text[:500])
        resp.raise_for_status()
        if not resp.content:
            return {}
        return resp.json()

    def get(self, path: str, **kwargs) -> dict:
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> dict:
        return self._request("POST", path, **kwargs)

    def delete(self, path: str, **kwargs) -> dict:
        return self._request("DELETE", path, **kwargs)

    # ---- profiles ----------------------------------------------------------

    def list_profiles(self) -> list[dict]:
        return self.get("/v2/profiles") or []

    # ---- webhook subscriptions --------------------------------------------

    def list_subscriptions(self, profile_id: int | str) -> list[dict]:
        return self.get(f"/v3/profiles/{profile_id}/subscriptions") or []

    def subscribe_webhook(
        self,
        profile_id: int | str,
        event_type: str,
        delivery_url: str,
        name: str | None = None,
    ) -> dict:
        body = {
            "name": name or f"auto-{event_type}",
            "trigger_on": event_type,
            "delivery": {"version": "2.0.0", "url": delivery_url},
        }
        return self.post(f"/v3/profiles/{profile_id}/subscriptions", json=body)

    def delete_subscription(self, profile_id: int | str, subscription_id: str) -> None:
        self.delete(f"/v3/profiles/{profile_id}/subscriptions/{subscription_id}")

    # ---- transfer enrichment (for balances#credit) ------------------------

    def get_transfer(self, transfer_id: int | str) -> dict:
        """Fetch a transfer to recover sender info missing from balance#credit."""
        return self.get(f"/v1/transfers/{transfer_id}")

    # ---- statements (SCA) — used by backfill ------------------------------

    def list_balances(self, profile_id: int | str) -> list[dict]:
        return self.get(
            f"/v4/profiles/{profile_id}/balances",
            params={"types": "STANDARD"},
        ) or []

    def get_balance_statement(
        self,
        profile_id: int | str,
        balance_id: int | str,
        currency: str,
        from_iso: str,
        to_iso: str,
        statement_type: str = "FLAT",
    ) -> dict:
        return self.get(
            f"/v1/profiles/{profile_id}/balance-statements/{balance_id}/statement.json",
            params={
                "currency": currency,
                "intervalStart": from_iso,
                "intervalEnd": to_iso,
                "type": statement_type,
            },
        )
