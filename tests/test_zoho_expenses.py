"""Tests for ExpenseService."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from zoho.expenses import Expense, ExpenseService


def test_create_expense_posts_correct_payload():
    client = MagicMock()
    client.post.return_value = {
        "code": 0,
        "expense": {
            "expense_id": "E-1042", "amount": 89.00, "currency_code": "USD",
            "date": "2026-06-01", "description": "Helium 10 Diamond plan",
            "status": "unpaid",
        },
    }

    svc = ExpenseService(client)
    expense = svc.create_expense(
        date="2026-06-01",
        amount=89.00,
        currency="USD",
        account_id="acc_software",
        vendor_id="zoho_vendor_h10",
        description="Helium 10 Diamond plan",
    )

    assert isinstance(expense, Expense)
    assert expense.expense_id == "E-1042"
    client.post.assert_called_once()
    args, kwargs = client.post.call_args
    assert args[0] == "expenses"
    body = kwargs["json"]
    assert body["amount"] == 89.00
    assert body["currency_code"] == "USD"


def test_attach_file_posts_multipart():
    client = MagicMock()
    client.post.return_value = {"code": 0, "message": "attached"}

    svc = ExpenseService(client)
    svc.attach_file(
        expense_id="E-1042",
        filename="helium10.pdf",
        content=b"%PDF...",
        content_type="application/pdf",
    )

    client.post.assert_called_once()
    args, kwargs = client.post.call_args
    assert args[0] == "expenses/E-1042/attachment"
    files = kwargs["files"]
    assert "attachment" in files
    fname, body, ctype = files["attachment"]
    assert fname == "helium10.pdf"
    assert body == b"%PDF..."
    assert ctype == "application/pdf"
