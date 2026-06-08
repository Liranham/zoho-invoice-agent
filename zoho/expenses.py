"""Zoho Books Expense service — create + attach file."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from zoho.client import ZohoClient

logger = logging.getLogger(__name__)


@dataclass
class Expense:
    expense_id: str
    amount: float
    currency_code: str
    date: str
    description: str
    status: str


class ExpenseService:
    def __init__(self, client: ZohoClient):
        self.client = client

    def _parse(self, raw: dict) -> Expense:
        return Expense(
            expense_id=raw.get("expense_id", ""),
            amount=float(raw.get("amount", 0)),
            currency_code=raw.get("currency_code", ""),
            date=raw.get("date", ""),
            description=raw.get("description", ""),
            status=raw.get("status", ""),
        )

    def create_expense(
        self,
        *,
        date: str,
        amount: float,
        currency: str,
        account_id: Optional[str] = None,
        vendor_id: Optional[str] = None,
        description: str = "",
        paid_through_account_id: Optional[str] = None,
        reference_number: Optional[str] = None,
        tax_amount: Optional[float] = None,
    ) -> Expense:
        body = {
            "date": date,
            "amount": amount,
            "currency_code": currency,
        }
        if account_id:
            body["account_id"] = account_id
        if vendor_id:
            body["vendor_id"] = vendor_id
        if description:
            body["description"] = description
        if paid_through_account_id:
            body["paid_through_account_id"] = paid_through_account_id
        if reference_number:
            body["reference_number"] = reference_number
        if tax_amount is not None:
            body["tax_amount"] = tax_amount

        data = self.client.post("expenses", json=body)
        raw = data.get("expense", data)
        return self._parse(raw)

    def attach_file(
        self,
        *,
        expense_id: str,
        filename: str,
        content: bytes,
        content_type: str,
    ) -> None:
        self.client.post(
            f"expenses/{expense_id}/attachment",
            files={"attachment": (filename, content, content_type)},
        )
        logger.info("Attached %s to expense %s", filename, expense_id)
