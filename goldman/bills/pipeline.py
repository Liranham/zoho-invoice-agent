"""Three-write pipeline: Supabase Storage -> Google Drive -> Zoho Expenses.

Per spec §7.1 — order is Supabase first (audit anchor), then Drive (human
backup), then Zoho (the ledger). Each leg is independently retriable.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(name: str) -> str:
    return _SAFE_NAME.sub("_", name)


@dataclass
class FileResult:
    bill_id: UUID
    in_storage: bool
    in_drive: bool
    in_zoho: bool
    storage_path: Optional[str]
    drive_file_id: Optional[str]
    drive_url: Optional[str]
    zoho_expense_id: Optional[str]
    error: Optional[str]

    def all_succeeded(self) -> bool:
        return self.in_storage and self.in_drive and self.in_zoho


def _storage_path(*, entity_slug: str, invoice_date: Optional[date], filename: str) -> str:
    d = invoice_date or date.today()
    return f"{entity_slug}/{d.year}/{d.month:02d}/{_safe_filename(filename)}"


def run_three_write_pipeline(
    *,
    bill_id: UUID,
    file_path: Path,
    mime_type: str,
    parse,
    entity_slug: str,
    entity_legal_name: str,
    storage,
    storage_bucket: str,
    drive_client,
    drive_folder_id: str,
    zoho_expenses,
    bills_repo,
) -> FileResult:
    content = file_path.read_bytes()
    storage_path = _storage_path(
        entity_slug=entity_slug,
        invoice_date=parse.invoice_date,
        filename=file_path.name,
    )

    result = FileResult(
        bill_id=bill_id,
        in_storage=False, in_drive=False, in_zoho=False,
        storage_path=None, drive_file_id=None, drive_url=None,
        zoho_expense_id=None, error=None,
    )

    # 1. SUPABASE STORAGE
    try:
        storage.upload(
            bucket=storage_bucket, path=storage_path,
            content=content, content_type=mime_type,
        )
        bills_repo.mark_storage_done(bill_id, storage_path=storage_path)
        result.in_storage = True
        result.storage_path = storage_path
    except Exception as e:
        msg = f"Storage write failed: {e}"
        logger.exception(msg)
        bills_repo.record_failure(bill_id, error=msg)
        result.error = msg
        return result   # Without Supabase, we don't trust the rest.

    # 2. GOOGLE DRIVE
    try:
        upload = drive_client.upload_file(
            name=file_path.name,
            parent_id=drive_folder_id,
            content=content,
            mime_type=mime_type,
        )
        bills_repo.mark_drive_done(
            bill_id,
            drive_file_id=upload["file_id"],
            drive_url=upload.get("url", ""),
        )
        result.in_drive = True
        result.drive_file_id = upload["file_id"]
        result.drive_url = upload.get("url", "")
    except Exception as e:
        msg = f"Drive write failed: {e}"
        logger.exception(msg)
        bills_repo.record_failure(bill_id, error=msg)
        result.error = msg
        return result    # Skip Zoho — retry can pick up from here.

    # 3. ZOHO EXPENSES
    try:
        expense = zoho_expenses.create_expense(
            date=parse.invoice_date.isoformat() if parse.invoice_date else date.today().isoformat(),
            amount=parse.amount,
            currency=parse.currency,
            description=(
                f"{parse.vendor} {parse.invoice_number or ''}".strip()
                + (f" ({entity_legal_name})" if entity_legal_name else "")
            ),
        )
        zoho_expenses.attach_file(
            expense_id=expense.expense_id,
            filename=file_path.name,
            content=content,
            content_type=mime_type,
        )
        bills_repo.mark_zoho_done(bill_id, zoho_expense_id=expense.expense_id)
        result.in_zoho = True
        result.zoho_expense_id = expense.expense_id
    except Exception as e:
        msg = f"Zoho write failed: {e}"
        logger.exception(msg)
        bills_repo.record_failure(bill_id, error=msg)
        result.error = msg
        return result

    return result
