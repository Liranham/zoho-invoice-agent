"""Wise (TransferWise) read-only client for Goldman.

Auth: Personal Token (set via WISE_API_TOKEN env var, never logged).
Scope: READ ONLY. We intentionally do NOT upload an SCA private key,
which means any write attempt at the API layer would fail with
'Strong Customer Authentication required'.

Endpoints used:
  GET /v1/profiles                                        list profiles
  GET /v4/profiles/{id}/balances?types=STANDARD           current balances
  GET /v1/profiles/{id}/transfers                         transfer history
  GET /v2/profiles/{id}/accounts                          recipient accounts
  GET /v1/profiles/{id}/balance-statements/{bid}/statement.csv
                                                          monthly statement
"""

from __future__ import annotations

import os
from typing import Optional

import requests


API_BASE = "https://api.wise.com"


class WiseConfigError(RuntimeError):
    pass


def _load_cached_profile() -> Optional[str]:
    try:
        from goldman_db.connection import app_conn
        with app_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT profile_id FROM goldman.wise_config WHERE id=1")
                row = cur.fetchone()
        return row[0] if row and row[0] else None
    except Exception:
        return None


def _persist_profile(profile_id: str, profile_name: str = "") -> None:
    try:
        from goldman_db.connection import app_conn
        with app_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO goldman.wise_config (id, profile_id, profile_name)
                    VALUES (1, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                       SET profile_id = EXCLUDED.profile_id,
                           profile_name = EXCLUDED.profile_name,
                           updated_at = now()
                    """,
                    (profile_id, profile_name),
                )
                conn.commit()
    except Exception:
        pass


class WiseClient:
    """Thin Wise client. Auto-discovers the business profile on first call."""

    def __init__(self, *, token: Optional[str] = None,
                 profile_id: Optional[str] = None):
        self.token = token or os.getenv("WISE_API_TOKEN", "")
        if not self.token:
            raise WiseConfigError("WISE_API_TOKEN not set.")
        self._profile_id: Optional[str] = (
            profile_id
            or os.getenv("WISE_PROFILE_ID")
            or _load_cached_profile()
        )

    # ---- low-level fetch -------------------------------------------------

    def _get(self, path: str, params: Optional[dict] = None,
              raw: bool = False) -> object:
        resp = requests.get(
            f"{API_BASE}{path}",
            headers={"Authorization": f"Bearer {self.token}",
                     "Accept": "application/json"},
            params=params or {}, timeout=30,
        )
        resp.raise_for_status()
        return resp if raw else resp.json()

    # ---- profile discovery ----------------------------------------------

    def profile_id(self) -> str:
        if self._profile_id:
            return self._profile_id
        profiles = self._get("/v1/profiles") or []
        # Prefer a BUSINESS profile (Wise returns lowercase "business");
        # fall back to the first one.
        business = next(
            (p for p in profiles
             if (p.get("type") or "").upper() == "BUSINESS"),
            None,
        )
        target = business or (profiles[0] if profiles else None)
        if not target:
            raise WiseConfigError("Wise returned no profiles.")
        pid = str(target.get("id"))
        name = (target.get("businessName")
                or target.get("details", {}).get("name")
                or target.get("details", {}).get("firstName", "") + " "
                + target.get("details", {}).get("lastName", "")).strip()
        _persist_profile(pid, name)
        self._profile_id = pid
        return pid

    def profile_info(self) -> dict:
        profiles = self._get("/v1/profiles") or []
        pid = self.profile_id()
        return next((p for p in profiles if str(p.get("id")) == pid), {})

    # ---- balances --------------------------------------------------------

    def balances(self, *, types: str = "STANDARD") -> list:
        """Returns one dict per currency: {id, currency, amount, reservedAmount, ...}.

        Tries v4 first; some older accounts only have v3/v1 balances enabled
        for personal profiles, so fall through gracefully.
        """
        pid = self.profile_id()
        for path, params in (
            (f"/v4/profiles/{pid}/balances", {"types": types}),
            (f"/v3/borderless-accounts", {"profileId": pid}),
            (f"/v1/borderless-accounts", {"profileId": pid}),
        ):
            try:
                data = self._get(path, params)
            except Exception:
                continue
            # v4 shape: list of balance objects directly OR {balances:[...]}.
            if isinstance(data, list) and data:
                # v3/v1 nest balances inside accounts[].balances
                if "balances" in data[0]:
                    flat = []
                    for acc in data:
                        flat.extend(acc.get("balances", []) or [])
                    if flat:
                        return flat
                return data
            if isinstance(data, dict) and data.get("balances"):
                return data["balances"]
        return []

    def diagnose(self) -> dict:
        """Return raw profile + balance probe results. Read-only diagnostic."""
        out = {"profiles": [], "balance_attempts": []}
        try:
            out["profiles"] = self._get("/v1/profiles") or []
        except Exception as e:
            out["profiles_error"] = str(e)[:200]
        pid = None
        try:
            pid = self.profile_id()
            out["selected_profile_id"] = pid
        except Exception as e:
            out["profile_id_error"] = str(e)[:200]
        if pid:
            for path, params in (
                (f"/v4/profiles/{pid}/balances", {"types": "STANDARD"}),
                (f"/v4/profiles/{pid}/balances", None),
                (f"/v3/borderless-accounts", {"profileId": pid}),
            ):
                try:
                    r = self._get(path, params)
                    out["balance_attempts"].append({
                        "path": path, "params": params,
                        "kind": type(r).__name__,
                        "preview": str(r)[:400],
                    })
                except Exception as e:
                    out["balance_attempts"].append({
                        "path": path, "params": params,
                        "error": str(e)[:200],
                    })
        return out

    # ---- transfers -------------------------------------------------------

    def transfers(self, *, created_after: str = "", created_before: str = "",
                   status: str = "", limit: int = 100) -> list:
        """List transfers. Dates in ISO-8601 (e.g. 2026-05-01T00:00:00Z)."""
        pid = self.profile_id()
        params = {"profile": pid, "limit": min(limit, 1000)}
        if created_after:
            params["createdDateStart"] = created_after
        if created_before:
            params["createdDateEnd"] = created_before
        if status:
            params["status"] = status
        return self._get("/v1/transfers", params) or []

    # ---- recipients ------------------------------------------------------

    def recipients(self, *, limit: int = 100) -> list:
        pid = self.profile_id()
        return self._get(f"/v2/profiles/{pid}/accounts",
                          {"size": min(limit, 200)}).get("content", []) or []

    # ---- statements ------------------------------------------------------

    def statement_csv_url(self, *, balance_id: str, start: str, stop: str) -> str:
        """Returns a CSV statement download URL for a balance over [start, stop].
        Dates ISO-8601 (e.g. 2026-05-01T00:00:00Z)."""
        pid = self.profile_id()
        # Wise serves statements at this path; the same URL with the auth
        # header returns the CSV directly.
        return (f"{API_BASE}/v1/profiles/{pid}/balance-statements/"
                 f"{balance_id}/statement.csv"
                 f"?currency=&intervalStart={start}&intervalEnd={stop}&type=COMPACT")

    def statement_csv(self, *, balance_id: str, start: str, stop: str) -> bytes:
        """Fetch the CSV statement as bytes."""
        pid = self.profile_id()
        resp = requests.get(
            f"{API_BASE}/v1/profiles/{pid}/balance-statements/"
            f"{balance_id}/statement.csv",
            headers={"Authorization": f"Bearer {self.token}"},
            params={"intervalStart": start, "intervalEnd": stop, "type": "COMPACT"},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.content
