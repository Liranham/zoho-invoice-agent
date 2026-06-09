"""
Process verified Wise webhook events into Zoho invoices.

This module is the bridge between a verified Wise webhook payload and the
existing invoice creation pipeline (`InvoiceGenerator` + `InvoiceService`).

It handles two event types:
  - swift-in#credit  : payload includes sender.name → straight-through invoice
  - balances#credit  : payload omits sender → enrich via GET /transfers/{id}
                       if we can extract a transfer id; otherwise Telegram-prompt.

Idempotency: a JSON file at WISE_STATE_PATH records the dedup keys we've
already invoiced. Composite key: "{event_type}:{resource_id}:{occurred_at}:{amount}".
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from invoice_templates import InvoiceGenerator
from wise.client import WiseClient
from zoho.contacts import ContactService
from zoho.invoices import InvoiceService

logger = logging.getLogger(__name__)


# Map normalized Wise sender names to Zoho customer IDs.
# (Same shape as gmail/automation.py CLIENT_MAPPING, kept independent so the
# Gmail flow can be retired without touching this.)
CLIENT_MAPPING = {
    "GILAD WEINBERG": "8399034000000100025",
    "AMZEXPERTGLOBALL": "8399034000000100007",
    "AMZ-EXPERT": "8399034000000100007",
}


class WiseAutomation:
    def __init__(
        self,
        wise_client: WiseClient,
        invoice_service: InvoiceService,
        contact_service: ContactService,
        telegram=None,
        state_path: str | None = None,
    ):
        self.wise = wise_client
        self.invoice_service = invoice_service
        self.contact_service = contact_service
        self.telegram = telegram
        self.state_path = Path(
            state_path or os.environ.get("WISE_STATE_PATH", "state/wise_processed.json")
        )
        self._state_lock = threading.Lock()
        self._processed = self._load_state()

    # ---- state -------------------------------------------------------------

    def _load_state(self) -> set[str]:
        try:
            return set(json.loads(self.state_path.read_text()))
        except (FileNotFoundError, json.JSONDecodeError):
            return set()
        except OSError as e:
            logger.warning("Cannot read wise state: %s", e)
            return set()

    def _save_state(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(sorted(self._processed)))
        except OSError as e:
            logger.warning("Cannot write wise state: %s — will re-process on retry", e)

    def _mark_processed(self, key: str) -> None:
        with self._state_lock:
            self._processed.add(key)
            self._save_state()

    def _is_processed(self, key: str) -> bool:
        with self._state_lock:
            return key in self._processed

    # ---- entry point -------------------------------------------------------

    def handle(self, payload: dict) -> bool:
        event_type = payload.get("event_type", "")
        if event_type == "swift-in#credit":
            return self._handle_swift_in(payload)
        if event_type == "balances#credit":
            return self._handle_balance_credit(payload)
        logger.info("Ignoring event type: %s", event_type)
        return False

    # ---- swift-in#credit ---------------------------------------------------

    def _handle_swift_in(self, payload: dict) -> bool:
        data = payload.get("data") or {}
        resource = data.get("resource") or {}
        sender = resource.get("sender") or {}

        sender_name = (sender.get("name") or "").strip()
        amount = self._extract_amount(data)
        currency = data.get("currency") or resource.get("currency") or "USD"
        occurred_at = data.get("occurred_at") or payload.get("sent_at") or ""

        dedup_key = self._dedup_key("swift-in", resource.get("id"), occurred_at, amount)
        if self._is_processed(dedup_key):
            logger.info("Already processed: %s", dedup_key)
            return False

        if amount is None or amount <= 0:
            logger.warning("Skipping swift-in with non-positive amount: %s", amount)
            return False

        return self._create_invoice(
            sender_name=sender_name,
            amount=amount,
            currency=currency,
            occurred_at=occurred_at,
            dedup_key=dedup_key,
            payload=payload,
        )

    # ---- balances#credit ---------------------------------------------------

    def _handle_balance_credit(self, payload: dict) -> bool:
        data = payload.get("data") or {}
        resource = data.get("resource") or {}
        amount = self._extract_amount(data)
        currency = data.get("currency") or "USD"
        occurred_at = data.get("occurred_at") or payload.get("sent_at") or ""

        dedup_key = self._dedup_key(
            "balance", resource.get("id"), occurred_at, amount
        )
        if self._is_processed(dedup_key):
            logger.info("Already processed: %s", dedup_key)
            return False

        if amount is None or amount <= 0:
            logger.warning("Skipping balance credit with non-positive amount: %s", amount)
            return False

        # Try to enrich. balances#credit doesn't carry sender, but some payloads
        # surface a transfer reference; if so, hit /v1/transfers/{id}.
        sender_name = self._try_enrich_sender(payload)

        return self._create_invoice(
            sender_name=sender_name,
            amount=amount,
            currency=currency,
            occurred_at=occurred_at,
            dedup_key=dedup_key,
            payload=payload,
        )

    def _try_enrich_sender(self, payload: dict) -> str:
        """Best-effort sender extraction for balance credits."""
        data = payload.get("data") or {}
        # Some payloads surface the originating transfer id as data.transfer_id
        # or data.resource.transfer_id — try both.
        transfer_id = data.get("transfer_id") or (data.get("resource") or {}).get("transfer_id")
        if not transfer_id:
            return ""
        try:
            transfer = self.wise.get_transfer(transfer_id)
            return (transfer.get("sourceAccount", {}).get("name")
                    or transfer.get("details", {}).get("sourceOfFunds")
                    or "").strip()
        except Exception as e:
            logger.warning("Sender enrichment failed for transfer %s: %s", transfer_id, e)
            return ""

    # ---- core invoice flow -------------------------------------------------

    def _create_invoice(
        self,
        sender_name: str,
        amount: float,
        currency: str,
        occurred_at: str,
        dedup_key: str,
        payload: dict,
    ) -> bool:
        wire_date = self._iso_to_date(occurred_at)
        customer_id = self._match_client(sender_name) if sender_name else None

        if not customer_id:
            logger.warning(
                "Unknown sender '%s' for $%.2f on %s — Telegram-prompting",
                sender_name, amount, wire_date,
            )
            self._notify_unknown_sender(sender_name, amount, currency, wire_date, dedup_key, payload)
            return False

        try:
            invoice_data = InvoiceGenerator.generate_invoice_data(
                client_name=sender_name,
                wire_amount=amount,
                wire_date=wire_date,
                customer_id=customer_id,
            )
        except ValueError as e:
            logger.error("No template for %s: %s", sender_name, e)
            self._telegram(f"⚠️ No template for sender: {sender_name}\nAmount: ${amount:.2f}")
            return False

        try:
            contact_person_ids = self.contact_service.get_contact_person_ids(customer_id)
        except Exception as e:
            logger.warning("Could not fetch contact persons for %s: %s", customer_id, e)
            contact_person_ids = []

        try:
            invoice = self.invoice_service.create_invoice(
                customer_id=customer_id,
                line_items=invoice_data["line_items"],
                date=invoice_data["date"],
                payment_terms=invoice_data["payment_terms"],
                notes=invoice_data["notes"],
                contact_persons=contact_person_ids,
            )
        except Exception as e:
            logger.exception("Invoice create failed: %s", e)
            self._telegram(
                f"❌ Invoice creation failed\nSender: {sender_name}\nAmount: ${amount:.2f}\nError: {e}"
            )
            return False

        # Mark idempotent BEFORE attempting to send email — even if email fails,
        # the invoice exists and we shouldn't recreate it.
        self._mark_processed(dedup_key)

        # Best-effort email
        if contact_person_ids:
            try:
                self.invoice_service.send_invoice(invoice.invoice_id)
                email_status = "📧 Emailed"
            except Exception as e:
                logger.warning("Email send failed: %s", e)
                email_status = f"⚠️ Email failed: {e}"
        else:
            email_status = "⚠️ No contact persons; not emailed"

        self._telegram(
            f"✅ Invoice created\n"
            f"Number: {invoice.invoice_number}\n"
            f"Client: {sender_name}\n"
            f"Amount: ${invoice.total:.2f}\n"
            f"{email_status}"
        )
        return True

    # ---- helpers -----------------------------------------------------------

    def _match_client(self, sender_name: str) -> Optional[str]:
        normalized = sender_name.upper().strip()
        if normalized in CLIENT_MAPPING:
            return CLIENT_MAPPING[normalized]
        for key, customer_id in CLIENT_MAPPING.items():
            if key in normalized or normalized in key:
                return customer_id
        return None

    def _notify_unknown_sender(
        self,
        sender_name: str,
        amount: float,
        currency: str,
        wire_date: str,
        dedup_key: str,
        payload: dict,
    ) -> None:
        if not self.telegram:
            return
        text = (
            f"⚠️ Unknown sender on Wise wire\n"
            f"Sender: {sender_name or '(empty)'}\n"
            f"Amount: {amount:.2f} {currency}\n"
            f"Date: {wire_date}\n\n"
            f"Choose how to handle:"
        )
        buttons = [
            [
                {"text": "→ Gilad", "callback_data": f"wise:map:GILAD:{dedup_key}"},
                {"text": "→ AMZ", "callback_data": f"wise:map:AMZEXPERTGLOBALL:{dedup_key}"},
            ],
            [{"text": "Skip", "callback_data": f"wise:skip:{dedup_key}"}],
        ]
        # Stash the original payload so the inbox handler can resume.
        try:
            pending_dir = self.state_path.parent / "pending"
            pending_dir.mkdir(parents=True, exist_ok=True)
            (pending_dir / f"{dedup_key.replace(':', '_')}.json").write_text(
                json.dumps(payload)
            )
        except OSError as e:
            logger.warning("Failed to stash pending payload: %s", e)

        if hasattr(self.telegram, "send_message_with_buttons"):
            self.telegram.send_message_with_buttons(text, buttons)
        else:
            self.telegram.send_message(text)

    def _telegram(self, text: str) -> None:
        if self.telegram:
            try:
                self.telegram.send_message(text)
            except Exception as e:
                logger.warning("Telegram send failed: %s", e)

    @staticmethod
    def _extract_amount(data: dict) -> Optional[float]:
        for key in ("amount", "post_transaction_balance_amount"):
            v = data.get(key)
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, dict) and "value" in v:
                try:
                    return float(v["value"])
                except (TypeError, ValueError):
                    continue
            if isinstance(v, str):
                try:
                    return float(v)
                except ValueError:
                    continue
        return None

    @staticmethod
    def _iso_to_date(iso: str) -> str:
        if not iso:
            return datetime.utcnow().strftime("%Y-%m-%d")
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%Y-%m-%d")
        except ValueError:
            return datetime.utcnow().strftime("%Y-%m-%d")

    @staticmethod
    def _dedup_key(prefix: str, resource_id, occurred_at: str, amount: Optional[float]) -> str:
        amt = f"{amount:.2f}" if amount is not None else "?"
        return f"{prefix}:{resource_id}:{occurred_at}:{amt}"
