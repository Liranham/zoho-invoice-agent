"""Postgres connection helpers for Goldman.

Returns plain psycopg.Connection objects via context managers.
Connection strings are read from GoldmanDbSettings at call time so tests
can override env vars before each call.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

import psycopg

from config.settings import GoldmanDbSettings

logger = logging.getLogger(__name__)


def _connect(url: str, role_label: str) -> psycopg.Connection:
    if not url:
        raise RuntimeError(
            f"Goldman DB {role_label} URL not configured. "
            f"Set GOLDMAN_DB_{role_label.upper()}_URL."
        )
    conn = psycopg.connect(url, autocommit=False)
    return conn


@contextmanager
def admin_conn() -> Iterator[psycopg.Connection]:
    """Yield an admin (super-admin / service-role) connection.

    Use only in migrator and admin scripts. Commits on success, rolls back
    on exception.
    """
    settings = GoldmanDbSettings()
    conn = _connect(settings.admin_url, "admin")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def app_conn() -> Iterator[psycopg.Connection]:
    """Yield an app (goldman_app role) connection — the default for runtime."""
    settings = GoldmanDbSettings()
    conn = _connect(settings.app_url, "app")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
