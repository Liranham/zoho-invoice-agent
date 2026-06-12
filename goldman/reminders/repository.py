"""CRUD on goldman.scheduled_reminders."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass
class Reminder:
    id: object
    name: str
    entity_slug: Optional[str]
    days_of_month: list
    action: str
    action_params: dict
    channel: str
    channel_id: str
    active: bool
    last_fired_at: Optional[datetime]
    next_due_date: date
    last_result_summary: Optional[str]


_COLS = ("id, name, entity_slug, days_of_month, action, action_params, "
         "channel, channel_id, active, last_fired_at, next_due_date, "
         "last_result_summary")


def _row(r) -> Reminder:
    return Reminder(
        id=r[0], name=r[1], entity_slug=r[2], days_of_month=list(r[3] or []),
        action=r[4], action_params=r[5] or {},
        channel=r[6], channel_id=r[7], active=r[8],
        last_fired_at=r[9], next_due_date=r[10], last_result_summary=r[11],
    )


class ReminderRepository:
    def __init__(self, conn):
        self.conn = conn

    def list_due(self, today: date) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_COLS} FROM goldman.scheduled_reminders
                WHERE active = TRUE AND next_due_date <= %s
                ORDER BY next_due_date
                """,
                (today,),
            )
            return [_row(r) for r in cur.fetchall()]

    def list_all(self, active_only: bool = False) -> list:
        with self.conn.cursor() as cur:
            if active_only:
                cur.execute(f"SELECT {_COLS} FROM goldman.scheduled_reminders "
                            "WHERE active = TRUE ORDER BY next_due_date")
            else:
                cur.execute(f"SELECT {_COLS} FROM goldman.scheduled_reminders "
                            "ORDER BY active DESC, next_due_date")
            return [_row(r) for r in cur.fetchall()]

    def get(self, reminder_id) -> Optional[Reminder]:
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT {_COLS} FROM goldman.scheduled_reminders "
                        "WHERE id = %s", (reminder_id,))
            row = cur.fetchone()
        return _row(row) if row else None

    def upsert_by_name(
        self, *, name: str, days_of_month: list, action: str,
        channel_id: str, entity_slug: Optional[str] = None,
        channel: str = "telegram", action_params: Optional[dict] = None,
        next_due_date: Optional[date] = None,
    ) -> Reminder:
        """Insert or update by `name` (case-insensitive). Returns the row."""
        if not days_of_month:
            raise ValueError("days_of_month must be non-empty")
        if not channel_id:
            raise ValueError("channel_id is required")
        nd = next_due_date or _next_due(date.today(), days_of_month)
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM goldman.scheduled_reminders
                WHERE lower(name) = lower(%s)
                """,
                (name,),
            )
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    f"""
                    UPDATE goldman.scheduled_reminders
                    SET name=%s, entity_slug=%s, days_of_month=%s,
                        action=%s, action_params=%s::jsonb,
                        channel=%s, channel_id=%s,
                        next_due_date=%s, active=TRUE
                    WHERE id=%s
                    RETURNING {_COLS}
                    """,
                    (name, entity_slug, days_of_month, action,
                     json.dumps(action_params or {}, default=str),
                     channel, channel_id, nd, existing[0]),
                )
            else:
                cur.execute(
                    f"""
                    INSERT INTO goldman.scheduled_reminders
                      (name, entity_slug, days_of_month, action,
                       action_params, channel, channel_id, next_due_date)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                    RETURNING {_COLS}
                    """,
                    (name, entity_slug, days_of_month, action,
                     json.dumps(action_params or {}, default=str),
                     channel, channel_id, nd),
                )
            return _row(cur.fetchone())

    def disable(self, reminder_id) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE goldman.scheduled_reminders SET active=FALSE "
                "WHERE id=%s",
                (reminder_id,),
            )

    def mark_fired(self, reminder_id, *, next_due_date: date,
                   result_summary: str = "") -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.scheduled_reminders
                SET last_fired_at = now(),
                    next_due_date = %s,
                    last_result_summary = %s
                WHERE id = %s
                """,
                (next_due_date, result_summary[:500] if result_summary else None,
                 reminder_id),
            )


def _next_due(today: date, days_of_month: list) -> date:
    """Compute the next firing date strictly AFTER today.

    Walk day-by-day up to ~62 days ahead until we hit a configured day-of-month.
    """
    from datetime import timedelta
    days = set(int(d) for d in days_of_month)
    for offset in range(1, 65):
        candidate = today + timedelta(days=offset)
        if candidate.day in days:
            return candidate
    raise ValueError("No upcoming match within 65 days; bad days_of_month.")


def next_due_from(today: date, days_of_month: list) -> date:
    """Public helper for callers (e.g. the tick handler)."""
    return _next_due(today, days_of_month)
