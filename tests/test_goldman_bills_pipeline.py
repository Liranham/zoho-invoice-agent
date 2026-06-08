"""Tests for the three-write pipeline."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from goldman.bills.pipeline import FileResult, run_three_write_pipeline
from goldman.bills.parser import BillParseResult


def _parse(amount=89.00):
    return BillParseResult(
        vendor="Helium 10", invoice_number="C0C-001",
        amount=amount, currency="USD",
        invoice_date=date(2026, 6, 1),
        due_date=None,
        billing_entity="AMZ Expert Global Limited",
        line_items=[], tax_amount=None, parse_confidence=0.95,
    )


def test_all_three_writes_succeed(tmp_path):
    f = tmp_path / "h10.pdf"
    f.write_bytes(b"%PDF...")

    bill_id = uuid4()
    bills_repo = MagicMock()
    storage = MagicMock()
    drive = MagicMock()
    drive.upload_file.return_value = {"file_id": "fid", "url": "https://..."}
    zoho_expenses = MagicMock()
    zoho_expenses.create_expense.return_value = MagicMock(expense_id="E-1042")

    result = run_three_write_pipeline(
        bill_id=bill_id,
        file_path=f,
        mime_type="application/pdf",
        parse=_parse(),
        entity_slug="amzg",
        entity_legal_name="AMZ Expert Global Limited",
        storage=storage,
        storage_bucket="goldman-bills",
        drive_client=drive,
        drive_folder_id="june_id",
        zoho_expenses=zoho_expenses,
        bills_repo=bills_repo,
    )

    storage.upload.assert_called_once()
    drive.upload_file.assert_called_once()
    zoho_expenses.create_expense.assert_called_once()
    zoho_expenses.attach_file.assert_called_once()
    bills_repo.mark_storage_done.assert_called_once()
    bills_repo.mark_drive_done.assert_called_once()
    bills_repo.mark_zoho_done.assert_called_once()
    assert result.all_succeeded() is True


def test_drive_failure_marks_partial_and_records_error(tmp_path):
    f = tmp_path / "h10.pdf"
    f.write_bytes(b"%PDF...")

    bills_repo = MagicMock()
    storage = MagicMock()
    drive = MagicMock()
    drive.upload_file.side_effect = RuntimeError("Drive 500")
    zoho_expenses = MagicMock()

    result = run_three_write_pipeline(
        bill_id=uuid4(),
        file_path=f,
        mime_type="application/pdf",
        parse=_parse(),
        entity_slug="amzg",
        entity_legal_name="AMZ Expert Global Limited",
        storage=storage,
        storage_bucket="goldman-bills",
        drive_client=drive,
        drive_folder_id="june_id",
        zoho_expenses=zoho_expenses,
        bills_repo=bills_repo,
    )

    bills_repo.mark_storage_done.assert_called_once()
    bills_repo.mark_drive_done.assert_not_called()
    bills_repo.record_failure.assert_called_once()
    zoho_expenses.create_expense.assert_not_called()
    assert result.all_succeeded() is False
    assert result.in_storage is True
    assert result.in_drive is False
    assert result.in_zoho is False
