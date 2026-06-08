"""Tests for the Goldman migrator.

Uses an in-memory fake Postgres connection (psycopg-style cursor mock) to
verify migration ordering, idempotency, and the bootstrap path where
goldman.migrations does not yet exist.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from goldman_db.migrator import _planned_migrations, apply_pending


def test_planned_migrations_sorts_by_filename(tmp_path: Path):
    (tmp_path / "0003_three.sql").write_text("-- three")
    (tmp_path / "0001_one.sql").write_text("-- one")
    (tmp_path / "0002_two.sql").write_text("-- two")
    (tmp_path / "ignored.txt").write_text("not sql")

    plan = _planned_migrations(tmp_path)

    assert [p.name for p in plan] == [
        "0001_one.sql",
        "0002_two.sql",
        "0003_three.sql",
    ]


def test_apply_pending_bootstraps_when_table_missing(tmp_path: Path):
    """First run: goldman.migrations doesn't exist; apply 0001 then record."""
    (tmp_path / "0001_init.sql").write_text("CREATE SCHEMA goldman;")

    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value

    # First fetchone() — table existence check — returns None (does not exist).
    # Second fetchone() — after we create migrations table — returns ().
    cur.fetchone.side_effect = [None, ()]
    cur.fetchall.return_value = []  # no rows in goldman.migrations after creation

    applied = apply_pending(conn, tmp_path)

    assert applied == ["0001_init.sql"]
    # Verify the SQL file content was executed
    assert any("CREATE SCHEMA goldman" in str(c) for c in cur.execute.call_args_list)


def test_apply_pending_skips_already_applied(tmp_path: Path):
    (tmp_path / "0001_one.sql").write_text("-- one")
    (tmp_path / "0002_two.sql").write_text("-- two")

    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value

    # Table exists; 0001 already applied
    cur.fetchone.return_value = (True,)
    cur.fetchall.return_value = [("0001_one.sql",)]

    applied = apply_pending(conn, tmp_path)

    assert applied == ["0002_two.sql"]


def test_apply_pending_records_each_migration(tmp_path: Path):
    (tmp_path / "0001_one.sql").write_text("SELECT 1;")

    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (True,)
    cur.fetchall.return_value = []

    apply_pending(conn, tmp_path)

    # Verify an INSERT into goldman.migrations was made for 0001_one.sql
    insert_calls = [
        c for c in cur.execute.call_args_list
        if "INSERT INTO goldman.migrations" in str(c)
    ]
    assert len(insert_calls) == 1
    assert "0001_one.sql" in str(insert_calls[0])
