"""Hubstaff v2 API client for Goldman.

Wraps the Personal Access Token (PAT) → access_token exchange and the
subset of /v2 endpoints we need for payroll thinking:

  - users/me, organizations, members (with users joined),
  - projects, activities/daily.

Auth flow (per https://developer.hubstaff.com/authentication):
  1. Liran generates a PAT at https://developer.hubstaff.com/personal_access_tokens.
  2. PAT lasts ~90 days. It's a refresh_token-shaped credential.
  3. Goldman exchanges it for a short-lived access_token (~24h) via
     POST https://account.hubstaff.com/access_tokens
     body: grant_type=refresh_token&refresh_token=<PAT>
  4. Use Authorization: Bearer <access_token> on every API call.

The exchange response also includes a NEW refresh_token (PAT rolls forward
on every use). We persist the latest PAT in goldman.facts so it survives
restarts; if HUBSTAFF_PAT env var is fresher we prefer that.
"""

from __future__ import annotations

import os
import time
from typing import Optional

import requests


API_BASE = "https://api.hubstaff.com/v2"
TOKEN_URL = "https://account.hubstaff.com/access_tokens"


class HubstaffConfigError(RuntimeError):
    pass


def _load_persisted_pat() -> Optional[str]:
    """Read the latest rolling refresh token from goldman.hubstaff_tokens.

    Failures (missing table, DB unavailable, etc.) fall back silently so
    the client keeps working from the env-var seed during early setup.
    """
    try:
        from goldman_db.connection import app_conn
        with app_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT refresh_token FROM goldman.hubstaff_tokens WHERE id=1"
                )
                row = cur.fetchone()
        return row[0] if row else None
    except Exception:
        return None


def _persist_pat(new_pat: str) -> None:
    """Write the rotated refresh token back so future processes pick it up."""
    try:
        from goldman_db.connection import app_conn
        with app_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO goldman.hubstaff_tokens (id, refresh_token)
                    VALUES (1, %s)
                    ON CONFLICT (id) DO UPDATE
                       SET refresh_token = EXCLUDED.refresh_token,
                           updated_at = now()
                    """,
                    (new_pat,),
                )
                conn.commit()
    except Exception:
        # Persistence failure is non-fatal — the in-memory PAT still works
        # for the lifetime of this process. The next process will fall back
        # to the env-var seed, which is the same situation we already had.
        pass


class HubstaffClient:
    """Single thin client. One per process is enough."""

    def __init__(self, *, pat: Optional[str] = None,
                 org_id: Optional[str] = None):
        # Priority order for the refresh token:
        #   1. explicit pat argument (tests, ad-hoc calls)
        #   2. goldman.hubstaff_tokens row (rolling state — survives rotation)
        #   3. HUBSTAFF_PAT env var (initial seed)
        self.pat = pat or _load_persisted_pat() or os.getenv("HUBSTAFF_PAT", "")
        self.org_id = str(org_id or os.getenv("HUBSTAFF_ORG_ID", "")).strip()
        if not self.pat:
            raise HubstaffConfigError("HUBSTAFF_PAT not set.")
        self._access_token: Optional[str] = None
        self._access_token_expires_at: float = 0.0

    # ---- auth -----------------------------------------------------------

    def _refresh_access_token(self) -> str:
        resp = requests.post(
            TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": self.pat},
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._access_token = payload["access_token"]
        # Use 90% of the lifetime as safety margin.
        ttl = int(payload.get("expires_in", 86400)) * 0.9
        self._access_token_expires_at = time.time() + ttl
        # Hubstaff rotates the refresh token on every exchange. Persist
        # the new one immediately so a process restart doesn't fall back
        # to the now-invalid env-var seed.
        new_pat = payload.get("refresh_token")
        if new_pat and new_pat != self.pat:
            self.pat = new_pat
            _persist_pat(new_pat)
        return self._access_token

    def _bearer(self) -> str:
        if not self._access_token or time.time() >= self._access_token_expires_at:
            self._refresh_access_token()
        return f"Bearer {self._access_token}"

    # ---- low-level fetch ------------------------------------------------

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        resp = requests.get(
            f"{API_BASE}{path}",
            headers={"Authorization": self._bearer()},
            params=params or {}, timeout=30,
        )
        # Auto-retry once on auth failure (token may have just expired).
        if resp.status_code == 401:
            self._refresh_access_token()
            resp = requests.get(
                f"{API_BASE}{path}",
                headers={"Authorization": self._bearer()},
                params=params or {}, timeout=30,
            )
        resp.raise_for_status()
        return resp.json()

    # ---- high-level endpoints used by Goldman ---------------------------

    def me(self) -> dict:
        return self._get("/users/me").get("user", {})

    def organizations(self) -> list:
        return self._get("/organizations").get("organizations", [])

    def members(self, org_id: Optional[str] = None) -> tuple:
        """Returns (members_list, users_lookup_by_id)."""
        oid = str(org_id or self.org_id)
        data = self._get(f"/organizations/{oid}/members", {"include": "users"})
        members = data.get("members", []) or []
        users = {u["id"]: u for u in data.get("users", [])}
        return members, users

    def projects(self, org_id: Optional[str] = None,
                  status: str = "active") -> list:
        oid = str(org_id or self.org_id)
        params = {"page_limit": 100}
        if status:
            params["status"] = status
        return self._get(f"/organizations/{oid}/projects", params).get("projects", [])

    def daily_activities(
        self, *, start: str, stop: str,
        org_id: Optional[str] = None,
        user_ids: Optional[list] = None,
        project_ids: Optional[list] = None,
    ) -> list:
        """Returns list of {date, user_id, project_id, tracked, billable, ...}.

        `start`/`stop` are YYYY-MM-DD strings (inclusive both ends per Hubstaff).
        """
        oid = str(org_id or self.org_id)
        params = {"date[start]": start, "date[stop]": stop, "page_limit": 500}
        if user_ids:
            params["user_ids[]"] = [str(u) for u in user_ids]
        if project_ids:
            params["project_ids[]"] = [str(p) for p in project_ids]
        out: list = []
        # Paginate.
        while True:
            data = self._get(f"/organizations/{oid}/activities/daily", params)
            rows = data.get("daily_activities", []) or []
            out.extend(rows)
            pagination = data.get("pagination") or {}
            next_id = pagination.get("next_id")
            if not next_id or len(rows) < params["page_limit"]:
                break
            params["page_start_id"] = next_id
        return out
