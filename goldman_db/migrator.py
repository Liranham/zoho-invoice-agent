"""Goldman migrator.

Applies pending .sql files from a migrations directory in filename order.
Tracked in goldman.migrations (created bootstrap-style when missing).

Designed for use with psycopg connections. The connection's transaction
boundary is the caller's responsibility — apply_pending uses one cursor
and commits at the end of each migration to preserve partial progress.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

import psycopg

logger = logging.getLogger(__name__)


_BOOTSTRAP_MIGRATIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS goldman.migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def _planned_migrations(migrations_dir: Path) -> list[Path]:
    """Return all .sql files in migrations_dir sorted by filename."""
    files = sorted(p for p in migrations_dir.iterdir() if p.suffix == ".sql")
    return files


def _migrations_table_exists(cur) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM pg_namespace n
        JOIN pg_class c ON c.relnamespace = n.oid
        WHERE n.nspname = 'goldman' AND c.relname = 'migrations'
        """
    )
    return cur.fetchone() is not None


def _already_applied(cur) -> set[str]:
    cur.execute("SELECT filename FROM goldman.migrations")
    return {row[0] for row in cur.fetchall()}


def apply_pending(
    conn: psycopg.Connection, migrations_dir: Path
) -> list[str]:
    """Apply any pending migrations. Returns the list of filenames applied."""
    plan = _planned_migrations(migrations_dir)
    if not plan:
        logger.info("No migration files found in %s", migrations_dir)
        return []

    applied: list[str] = []
    with conn.cursor() as cur:
        has_table = _migrations_table_exists(cur)

        if not has_table:
            # Bootstrap path: apply the first migration (which MUST create
            # the goldman schema), then create the migrations table, then
            # record the first migration.
            first = plan[0]
            logger.info("Bootstrap: applying %s", first.name)
            cur.execute(first.read_text())
            cur.execute(_BOOTSTRAP_MIGRATIONS_TABLE_SQL)
            cur.execute(
                "INSERT INTO goldman.migrations (filename) VALUES (%s)",
                (first.name,),
            )
            applied.append(first.name)
            conn.commit()
            plan = plan[1:]

        done = _already_applied(cur)
        for migration in plan:
            if migration.name in done:
                continue
            logger.info("Applying %s", migration.name)
            cur.execute(migration.read_text())
            cur.execute(
                "INSERT INTO goldman.migrations (filename) VALUES (%s)",
                (migration.name,),
            )
            applied.append(migration.name)
            conn.commit()

    return applied
