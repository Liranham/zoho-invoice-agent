"""
Test the WiseAutomation event handler with mocked Zoho/Wise services.

Asserts:
  - swift-in#credit with known sender → invoice created with correct amount/date/contact_persons
  - balances#credit (no enrichment) → unknown-sender Telegram prompt
  - duplicate delivery → idempotent (no second invoice)
  - non-target event types → ignored
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from wise.handler import WiseAutomation


GILAD_PAYLOAD = {
    "event_type": "swift-in#credit",
    "schema_version": "2.0.0",
    "sent_at": "2026-04-24T12:18:04Z",
    "data": {
        "resource": {
            "type": "transfer",
            "id": 2094761956,
            "profile_id": 12345,
            "sender": {"name": "GILAD WEINBERG", "account": "GB12..."},
        },
        "amount": 4493.89,
        "currency": "USD",
        "occurred_at": "2026-04-24T12:18:01Z",
    },
}

BALANCE_CREDIT_PAYLOAD = {
    "event_type": "balances#credit",
    "schema_version": "2.0.0",
    "sent_at": "2026-04-24T17:00:01Z",
    "data": {
        "resource": {"type": "balance-account", "id": 999, "profile_id": 12345},
        "transaction_type": "credit",
        "amount": 2997.0,
        "currency": "USD",
        "occurred_at": "2026-04-24T17:00:00Z",
    },
}


def _build_automation(state_dir: Path):
    invoice = MagicMock()
    invoice.invoice_id = "8399034000000999001"
    invoice.invoice_number = "INV-TEST-1"
    invoice.total = 4493.89

    invoice_service = MagicMock()
    invoice_service.create_invoice.return_value = invoice
    invoice_service.send_invoice.return_value = True

    contact_service = MagicMock()
    contact_service.get_contact_person_ids.return_value = ["8399034000000100027"]

    wise_client = MagicMock()
    telegram = MagicMock()

    automation = WiseAutomation(
        wise_client=wise_client,
        invoice_service=invoice_service,
        contact_service=contact_service,
        telegram=telegram,
        state_path=str(state_dir / "wise_processed.json"),
    )
    return automation, invoice_service, contact_service, telegram


def test_swift_in_credit_creates_invoice(tmp_path):
    automation, invoice_service, contact_service, telegram = _build_automation(tmp_path)

    ok = automation.handle(GILAD_PAYLOAD)
    assert ok is True

    invoice_service.create_invoice.assert_called_once()
    kwargs = invoice_service.create_invoice.call_args.kwargs
    assert kwargs["customer_id"] == "8399034000000100025"  # Gilad
    assert kwargs["date"] == "2026-04-24"
    assert kwargs["contact_persons"] == ["8399034000000100027"]
    # Line items: $50 admin + $4443.89 payroll
    rates = sorted(item["rate"] for item in kwargs["line_items"])
    assert rates == [50.0, 4443.89]

    invoice_service.send_invoice.assert_called_once_with("8399034000000999001")
    telegram.send_message.assert_called()


def test_swift_in_credit_is_idempotent(tmp_path):
    automation, invoice_service, _, _ = _build_automation(tmp_path)

    automation.handle(GILAD_PAYLOAD)
    automation.handle(GILAD_PAYLOAD)  # replay

    # Only one invoice should have been created
    assert invoice_service.create_invoice.call_count == 1


def test_balance_credit_unknown_sender_prompts_telegram(tmp_path):
    automation, invoice_service, _, telegram = _build_automation(tmp_path)

    ok = automation.handle(BALANCE_CREDIT_PAYLOAD)
    assert ok is False  # not auto-created
    invoice_service.create_invoice.assert_not_called()
    telegram.send_message_with_buttons.assert_called_once()

    # Verify the pending file was stashed
    pending_dir = Path(automation.state_path).parent / "pending"
    files = list(pending_dir.glob("*.json"))
    assert len(files) == 1
    stashed = json.loads(files[0].read_text())
    assert stashed["event_type"] == "balances#credit"


def test_unknown_event_type_ignored(tmp_path):
    automation, invoice_service, _, telegram = _build_automation(tmp_path)
    ok = automation.handle({"event_type": "transfers#state-change", "data": {}})
    assert ok is False
    invoice_service.create_invoice.assert_not_called()
    telegram.send_message_with_buttons.assert_not_called()


def test_state_persists_across_instances(tmp_path):
    state_path = tmp_path / "wise_processed.json"
    a1, inv1, _, _ = _build_automation(tmp_path)
    a1.handle(GILAD_PAYLOAD)
    assert inv1.create_invoice.call_count == 1

    # New automation instance, same state file
    a2, inv2, _, _ = _build_automation(tmp_path)
    assert state_path.exists()
    a2.handle(GILAD_PAYLOAD)
    inv2.create_invoice.assert_not_called()
