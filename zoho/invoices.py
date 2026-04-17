"""Zoho Books Invoice service — create, list, get, delete invoices."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from zoho.client import ZohoClient

logger = logging.getLogger(__name__)


@dataclass
class Invoice:
    invoice_id: str
    invoice_number: str
    status: str
    customer_name: str
    date: str
    due_date: str
    total: float
    balance: float
    currency_code: str
    line_items: list[dict] = field(default_factory=list)


class InvoiceService:
    def __init__(self, client: ZohoClient):
        self.client = client

    def _parse(self, raw: dict) -> Invoice:
        return Invoice(
            invoice_id=raw.get("invoice_id", ""),
            invoice_number=raw.get("invoice_number", ""),
            status=raw.get("status", ""),
            customer_name=raw.get("customer_name", ""),
            date=raw.get("date", ""),
            due_date=raw.get("due_date", ""),
            total=float(raw.get("total", 0)),
            balance=float(raw.get("balance", 0)),
            currency_code=raw.get("currency_code", ""),
            line_items=raw.get("line_items", []),
        )

    def list_invoices(
        self, status: str = "", page: int = 1, per_page: int = 25
    ) -> list[Invoice]:
        params = {"page": page, "per_page": per_page}
        if status:
            params["status"] = status
        data = self.client.get("invoices", params=params)
        return [self._parse(inv) for inv in data.get("invoices", [])]

    def get_invoice(self, invoice_id: str) -> Invoice | None:
        data = self.client.get(f"invoices/{invoice_id}")
        inv = data.get("invoice")
        return self._parse(inv) if inv else None

    def create_invoice(
        self,
        customer_id: str,
        line_items: list[dict],
        date: str = "",
        payment_terms: int = 30,
        notes: str = "",
        invoice_number: str = "",
    ) -> Invoice:
        body = {
            "customer_id": customer_id,
            "line_items": line_items,
            "payment_terms": payment_terms,
        }
        if date:
            body["date"] = date
        if notes:
            body["notes"] = notes
        if invoice_number:
            body["invoice_number"] = invoice_number

        data = self.client.post("invoices", json=body)
        inv = data.get("invoice", data)
        logger.info(
            "Invoice created: %s — %s",
            inv.get("invoice_id"),
            inv.get("invoice_number"),
        )
        return self._parse(inv)

    def delete_invoice(self, invoice_id: str) -> bool:
        self.client.delete(f"invoices/{invoice_id}")
        logger.info("Invoice deleted: %s", invoice_id)
        return True

    def send_invoice(self, invoice_id: str) -> bool:
        """Email an invoice to the customer."""
        self.client.post(f"invoices/{invoice_id}/email")
        logger.info("Invoice emailed: %s", invoice_id)
        return True
