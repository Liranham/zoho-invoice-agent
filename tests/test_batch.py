"""Tests for the batch processor."""

import csv
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import openpyxl

from batch.processor import BatchProcessor
from config.settings import InvoiceDefaults


def _make_processor(
    create_side_effect=None,
    default_customer_id="cust_default",
    default_item_id="item_default",
):
    invoice_svc = MagicMock()
    contact_svc = MagicMock()
    item_svc = MagicMock()
    defaults = InvoiceDefaults.__new__(InvoiceDefaults)
    defaults.default_customer_id = default_customer_id
    defaults.default_item_id = default_item_id
    defaults.payment_terms = 30

    if create_side_effect:
        invoice_svc.create_invoice.side_effect = create_side_effect
    else:
        invoice_svc.create_invoice.return_value = MagicMock(
            invoice_id="inv_new", invoice_number="INV-100", total=100.0
        )

    return BatchProcessor(invoice_svc, contact_svc, item_svc, defaults), invoice_svc


def _create_csv(rows: list[dict]) -> str:
    """Create a temp CSV file and return its path."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="")
    writer = csv.DictWriter(tmp, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    tmp.close()
    return tmp.name


def _create_excel(rows: list[dict]) -> str:
    """Create a temp Excel file and return its path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    tmp.close()
    wb = openpyxl.Workbook()
    ws = wb.active
    headers = list(rows[0].keys())
    ws.append(headers)
    for row in rows:
        ws.append([row[h] for h in headers])
    wb.save(tmp.name)
    return tmp.name


def test_read_csv():
    path = _create_csv([
        {"date": "2026-01-15", "amount": "500"},
        {"date": "2026-02-01", "amount": "750"},
    ])
    proc, _ = _make_processor()
    rows = proc.read_file(path)
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-01-15"
    assert rows[1]["amount"] == "750"


def test_read_excel():
    path = _create_excel([
        {"date": "2026-01-15", "amount": 500},
        {"date": "2026-02-01", "amount": 750},
    ])
    proc, _ = _make_processor()
    rows = proc.read_file(path)
    assert len(rows) == 2
    assert rows[0]["amount"] == 500


def test_batch_create_csv_dry_run():
    path = _create_csv([
        {"date": "2026-01-15", "amount": "500"},
        {"date": "2026-02-01", "amount": "750"},
    ])
    proc, inv_svc = _make_processor()
    result = proc.execute(path, dry_run=True)

    assert result.total == 2
    assert result.succeeded == 0  # dry run doesn't create
    assert result.failed == 0
    inv_svc.create_invoice.assert_not_called()


def test_batch_create_csv_real():
    path = _create_csv([
        {"date": "2026-01-15", "amount": "500"},
        {"date": "2026-02-01", "amount": "750"},
    ])
    proc, inv_svc = _make_processor()
    result = proc.execute(path, dry_run=False)

    assert result.succeeded == 2
    assert result.failed == 0
    assert inv_svc.create_invoice.call_count == 2


def test_batch_skips_invalid_rows():
    path = _create_csv([
        {"date": "2026-01-15", "amount": "500"},
        {"date": "", "amount": "750"},  # missing date
        {"date": "2026-03-01", "amount": "-10"},  # negative amount
    ])
    proc, inv_svc = _make_processor()
    result = proc.execute(path, dry_run=False)

    assert result.succeeded == 1
    assert result.failed == 2
    assert len(result.errors) == 2


def test_batch_uses_customer_id_from_row():
    path = _create_csv([
        {"date": "2026-01-15", "amount": "500", "customer_id": "cust_explicit"},
    ])
    proc, inv_svc = _make_processor()
    proc.execute(path, dry_run=False)

    call_args = inv_svc.create_invoice.call_args
    assert call_args.kwargs["customer_id"] == "cust_explicit"


def test_batch_resolves_customer_name():
    path = _create_csv([
        {"date": "2026-01-15", "amount": "500", "customer_name": "Acme Corp"},
    ])
    proc, inv_svc = _make_processor(default_customer_id="")
    proc.contacts.get_customer_id.return_value = "cust_resolved"
    proc.execute(path, dry_run=False)

    proc.contacts.get_customer_id.assert_called_once_with("Acme Corp")
    call_args = inv_svc.create_invoice.call_args
    assert call_args.kwargs["customer_id"] == "cust_resolved"


def test_unsupported_file_type():
    proc, _ = _make_processor()
    try:
        proc.read_file("data.json")
        assert False, "Should have raised"
    except ValueError as e:
        assert "Unsupported" in str(e)
