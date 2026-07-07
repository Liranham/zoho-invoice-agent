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
    customer_id: str = ""
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
            customer_id=raw.get("customer_id", ""),
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

    def find_by_number(self, invoice_number: str) -> Invoice | None:
        """Look up an invoice by its human invoice number (e.g. 'INV-22').

        Zoho's per-invoice endpoints key on the internal numeric invoice_id,
        NOT the display number — passing the number 404s. This resolves a
        number to the real record so callers can accept either form.
        """
        data = self.client.get(
            "invoices", params={"invoice_number": invoice_number}
        )
        invoices = data.get("invoices", [])
        return self._parse(invoices[0]) if invoices else None

    def create_invoice(
        self,
        customer_id: str,
        line_items: list[dict],
        date: str = "",
        payment_terms: int = 30,
        notes: str = "",
        invoice_number: str = "",
        contact_persons: list[str] | None = None,
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
        if contact_persons:
            body["contact_persons"] = contact_persons

        data = self.client.post("invoices", json=body)
        inv = data.get("invoice", data)
        logger.info(
            "Invoice created: %s — %s",
            inv.get("invoice_id"),
            inv.get("invoice_number"),
        )
        return self._parse(inv)

    def update_invoice(self, invoice_id: str, **fields) -> Invoice:
        data = self.client.put(f"invoices/{invoice_id}", json=fields)
        inv = data.get("invoice", data)
        return self._parse(inv)

    def delete_invoice(self, invoice_id: str) -> bool:
        self.client.delete(f"invoices/{invoice_id}")
        logger.info("Invoice deleted: %s", invoice_id)
        return True

    def send_invoice(
        self,
        invoice_id: str,
        contact_persons: list[str] | None = None,
        to_mail_ids: list[str] | None = None,
        subject: str = "",
        body: str = "",
    ) -> bool:
        """Email an invoice to the customer.

        Zoho's /email endpoint 400s ("no contact persons associated") when
        the invoice has no recipients, so pass the customer's contact_persons
        and/or to_mail_ids explicitly.
        """
        payload: dict = {}
        if contact_persons:
            payload["contact_persons"] = contact_persons
        if to_mail_ids:
            payload["to_mail_ids"] = to_mail_ids
        if subject:
            payload["subject"] = subject
        if body:
            payload["body"] = body
        self.client.post(f"invoices/{invoice_id}/email", json=payload)
        logger.info("Invoice emailed: %s", invoice_id)
        return True

    def record_payment(
        self,
        invoice_id: str,
        customer_id: str,
        amount: float,
        account_id: str,
        date: str = "",
        payment_mode: str = "banktransfer",
        reference_number: str = "",
    ) -> dict:
        """Record a customer payment against an invoice (marks it paid).

        Creating a customer payment in Zoho Books applies `amount` to the
        invoice, reducing its balance — a full payment moves the invoice to
        status "paid". `account_id` is the deposit ("paid through") bank/cash
        account. Returns the raw Zoho payment dict (includes payment_id).
        """
        body = {
            "customer_id": customer_id,
            "payment_mode": payment_mode,
            "amount": float(amount),
            "account_id": account_id,
            "invoices": [
                {"invoice_id": invoice_id, "amount_applied": float(amount)}
            ],
        }
        if date:
            body["date"] = date
        if reference_number:
            body["reference_number"] = reference_number

        data = self.client.post("customerpayments", json=body)
        payment = data.get("payment", data)
        logger.info(
            "Payment recorded: %s — invoice %s, amount %s",
            payment.get("payment_id"), invoice_id, amount,
        )
        return payment
