"""Repository for goldman.bills."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

import psycopg


class DuplicateBillError(Exception):
    """Raised when a bill with the same idempotency_hash already exists."""


@dataclass(frozen=True)
class Bill:
    id: UUID
    entity_id: UUID
    vendor_id: Optional[UUID]
    vendor_name_at_intake: str
    invoice_number: Optional[str]
    invoice_date: Optional[date]
    amount: Decimal
    currency: str
    due_date: Optional[date]
    line_items: list
    tax_amount: Optional[Decimal]
    idempotency_hash: str
    original_filename: Optional[str]
    in_storage: bool
    storage_path: Optional[str]
    in_drive: bool
    drive_file_id: Optional[str]
    drive_url: Optional[str]
    in_zoho: bool
    zoho_expense_id: Optional[str]
    auto_filed: bool
    confirm_required: bool
    confirm_reason: Optional[str]
    status: str
    last_write_attempt_at: Optional[object]
    last_error: Optional[str]


_COLS = """
    id, entity_id, vendor_id, vendor_name_at_intake, invoice_number,
    invoice_date, amount, currency, due_date, line_items, tax_amount,
    idempotency_hash, original_filename,
    in_storage, storage_path, in_drive, drive_file_id, drive_url,
    in_zoho, zoho_expense_id,
    auto_filed, confirm_required, confirm_reason,
    status, last_write_attempt_at, last_error
"""


def _row(r) -> Bill:
    return Bill(
        id=r[0], entity_id=r[1], vendor_id=r[2],
        vendor_name_at_intake=r[3], invoice_number=r[4],
        invoice_date=r[5], amount=r[6], currency=r[7],
        due_date=r[8], line_items=r[9] or [], tax_amount=r[10],
        idempotency_hash=r[11], original_filename=r[12],
        in_storage=r[13], storage_path=r[14],
        in_drive=r[15], drive_file_id=r[16], drive_url=r[17],
        in_zoho=r[18], zoho_expense_id=r[19],
        auto_filed=r[20], confirm_required=r[21], confirm_reason=r[22],
        status=r[23], last_write_attempt_at=r[24], last_error=r[25],
    )


class BillRepository:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def insert(
        self,
        *,
        entity_id: UUID,
        vendor_name_at_intake: str,
        amount,
        currency: str,
        idempotency_hash: str,
        invoice_number: Optional[str] = None,
        invoice_date: Optional[date] = None,
        due_date: Optional[date] = None,
        line_items: Optional[list] = None,
        tax_amount: Optional[float] = None,
        original_filename: Optional[str] = None,
        vendor_id: Optional[UUID] = None,
    ) -> UUID:
        import json
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO goldman.bills
                        (entity_id, vendor_id, vendor_name_at_intake,
                         invoice_number, invoice_date, amount, currency,
                         due_date, line_items, tax_amount, idempotency_hash,
                         original_filename)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                    RETURNING id
                    """,
                    (entity_id, vendor_id, vendor_name_at_intake,
                     invoice_number, invoice_date, amount, currency,
                     due_date, json.dumps(line_items or []),
                     tax_amount, idempotency_hash, original_filename),
                )
                return cur.fetchone()[0]
        except psycopg.errors.UniqueViolation as e:
            raise DuplicateBillError(idempotency_hash) from e

    def get_by_idempotency_hash(self, idempotency_hash: str) -> Optional[Bill]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM goldman.bills WHERE idempotency_hash = %s",
                (idempotency_hash,),
            )
            row = cur.fetchone()
            return _row(row) if row else None

    def get(self, bill_id: UUID) -> Optional[Bill]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"SELECT {_COLS} FROM goldman.bills WHERE id = %s",
                (bill_id,),
            )
            row = cur.fetchone()
            return _row(row) if row else None

    def mark_storage_done(self, bill_id: UUID, *, storage_path: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.bills
                SET in_storage = true, storage_path = %s,
                    last_write_attempt_at = now(),
                    status = CASE
                        WHEN in_drive AND in_zoho THEN 'complete'
                        ELSE 'partial'
                    END
                WHERE id = %s
                """,
                (storage_path, bill_id),
            )

    def mark_drive_done(
        self, bill_id: UUID, *, drive_file_id: str, drive_url: str,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.bills
                SET in_drive = true, drive_file_id = %s, drive_url = %s,
                    last_write_attempt_at = now(),
                    status = CASE
                        WHEN in_storage AND in_zoho THEN 'complete'
                        ELSE 'partial'
                    END
                WHERE id = %s
                """,
                (drive_file_id, drive_url, bill_id),
            )

    def mark_zoho_done(self, bill_id: UUID, *, zoho_expense_id: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.bills
                SET in_zoho = true, zoho_expense_id = %s,
                    last_write_attempt_at = now(),
                    status = CASE
                        WHEN in_storage AND in_drive THEN 'complete'
                        ELSE 'partial'
                    END
                WHERE id = %s
                """,
                (zoho_expense_id, bill_id),
            )

    def record_failure(self, bill_id: UUID, *, error: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.bills
                SET last_error = %s,
                    last_write_attempt_at = now(),
                    status = CASE
                        WHEN in_storage OR in_drive OR in_zoho THEN 'partial'
                        ELSE 'failed'
                    END
                WHERE id = %s
                """,
                (error, bill_id),
            )

    def list_pending_partial_writes(self, *, limit: int = 20) -> list:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_COLS} FROM goldman.bills
                WHERE status IN ('partial', 'pending')
                  AND in_storage = true
                ORDER BY last_write_attempt_at ASC NULLS FIRST
                LIMIT %s
                """,
                (limit,),
            )
            return [_row(r) for r in cur.fetchall()]

    def mark_confirmation_required(
        self, bill_id: UUID, *, reason: str,
    ) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE goldman.bills
                SET confirm_required = true, confirm_reason = %s
                WHERE id = %s
                """,
                (reason, bill_id),
            )

    def mark_auto_filed(self, bill_id: UUID) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE goldman.bills SET auto_filed = true WHERE id = %s",
                (bill_id,),
            )
