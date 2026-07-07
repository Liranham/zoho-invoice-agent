"""Phase 9 — Zoho cross-entity safety guardrail."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from goldman.bot.tools import execute_tool
from goldman.zoho_safety import (
    EntityInfo, banner, needs_confirmation, confirmation_prompt,
    resolve_entity, UnknownEntityError,
)


# ---------- pure helpers ----------

def test_banner_includes_legal_name_and_org_id():
    info = EntityInfo(slug="amzg",
                       legal_name="AMZ-Expert Global Limited",
                       org_id="876247837")
    out = banner(info)
    assert "AMZ-Expert Global Limited" in out
    assert "876247837" in out
    assert "amzg" in out


def test_needs_confirmation_blocks_unconfirmed_writes():
    assert needs_confirmation("create_invoice", {}) is True
    assert needs_confirmation("create_expense", {}) is True
    assert needs_confirmation("create_customer", {}) is True
    assert needs_confirmation("send_invoice", {}) is True


def test_needs_confirmation_blocks_mark_invoice_paid():
    assert needs_confirmation("mark_invoice_paid", {}) is True
    assert needs_confirmation("mark_invoice_paid", {"confirmed": True}) is False


def test_needs_confirmation_passes_when_confirmed():
    assert needs_confirmation("create_invoice", {"confirmed": True}) is False


def test_needs_confirmation_never_blocks_reads():
    assert needs_confirmation("list_invoices", {}) is False
    assert needs_confirmation("list_customers", {}) is False


def test_confirmation_prompt_names_entity_and_action():
    info = EntityInfo(slug="seo",
                       legal_name="Pacific Edge Outsourcing LLC",
                       org_id="914942331")
    out = confirmation_prompt(info, "create_invoice", {
        "customer_id": "C1", "amount": 1500, "description": "May fees",
    })
    assert "Pacific Edge Outsourcing LLC" in out
    assert "914942331" in out
    assert "CONFIRMATION REQUIRED" in out
    assert "1500" in out
    assert "confirmed: true" in out


# ---------- resolve_entity ----------

def _conn_with_entity(slug, legal, org):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (slug, legal, org)
    return conn


def test_resolve_entity_returns_triple():
    conn = _conn_with_entity("seo", "Pacific Edge Outsourcing LLC", "914942331")
    info = resolve_entity(conn, "seo")
    assert info.slug == "seo"
    assert info.org_id == "914942331"


def test_resolve_entity_raises_when_slug_missing():
    conn = MagicMock()
    with pytest.raises(UnknownEntityError):
        resolve_entity(conn, "")


def test_resolve_entity_raises_when_no_zoho_org():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = ("amzg", "AMZ-Expert Global Limited", None)
    with pytest.raises(UnknownEntityError, match="no Zoho organization"):
        resolve_entity(conn, "amzg")


# ---------- end-to-end through the bot dispatcher ----------

def _ctx_with_entity(slug, legal, org):
    ctx = MagicMock()
    ctx.conn = _conn_with_entity(slug, legal, org)
    ctx.chat_id = "test-channel"
    return ctx


def test_create_invoice_first_call_returns_confirmation_prompt():
    ctx = _ctx_with_entity("seo", "Pacific Edge Outsourcing LLC", "914942331")
    out = execute_tool(
        ctx=ctx, name="create_invoice",
        arguments={"entity": "seo", "customer_id": "C1", "amount": 1500},
    )
    assert "CONFIRMATION REQUIRED" in out
    assert "Pacific Edge Outsourcing LLC" in out
    assert "914942331" in out
    # Crucially: did NOT touch the Zoho service.


def test_create_invoice_with_confirmed_true_proceeds_to_zoho():
    ctx = _ctx_with_entity("seo", "Pacific Edge Outsourcing LLC", "914942331")
    fake_invoice = MagicMock(
        invoice_number="INV-100", customer_name="Gilad",
        total=1500.0, currency_code="USD",
    )
    fake_svc = MagicMock()
    fake_svc.create_invoice.return_value = fake_invoice
    with patch("goldman.bot.tools._zoho_services_for",
                return_value=(fake_svc, MagicMock(), MagicMock(), MagicMock())):
        out = execute_tool(
            ctx=ctx, name="create_invoice",
            arguments={"entity": "seo", "customer_id": "C1",
                       "amount": 1500, "confirmed": True},
        )
    assert "INV-100" in out
    assert "Pacific Edge Outsourcing LLC" in out
    fake_svc.create_invoice.assert_called_once()


def test_create_invoice_multiline_maps_line_items_to_service():
    ctx = _ctx_with_entity("seo", "Pacific Edge Outsourcing LLC", "914942331")
    fake_invoice = MagicMock(
        invoice_id="ZID-22", invoice_number="INV-22", customer_name="Gilad Weinberg",
        total=2993.89, currency_code="USD",
    )
    fake_svc = MagicMock()
    fake_svc.create_invoice.return_value = fake_invoice
    with patch("goldman.bot.tools._zoho_services_for",
                return_value=(fake_svc, MagicMock(), MagicMock(), MagicMock())):
        out = execute_tool(
            ctx=ctx, name="create_invoice",
            arguments={
                "entity": "seo", "customer_id": "C1", "confirmed": True,
                "line_items": [
                    {"description": "Philippine VA contractor staffing services — cost reimbursement + service fee",
                     "rate": 2943.89, "quantity": 1, "account_id": "acct_sales"},
                    {"description": "Service fee", "rate": 50, "quantity": 1, "account_id": "acct_sales"},
                ],
            },
        )
    assert "INV-22" in out
    assert "ZID-22" in out  # invoice_id surfaced so the caller can chain mark_invoice_paid
    li = fake_svc.create_invoice.call_args.kwargs["line_items"]
    assert len(li) == 2
    assert li[0]["rate"] == 2943.89
    assert li[0]["account_id"] == "acct_sales"
    assert li[1]["description"] == "Service fee"
    assert li[1]["rate"] == 50.0


def test_mark_invoice_paid_first_call_returns_confirmation_prompt():
    ctx = _ctx_with_entity("seo", "Pacific Edge Outsourcing LLC", "914942331")
    out = execute_tool(
        ctx=ctx, name="mark_invoice_paid",
        arguments={"entity": "seo", "invoice_id": "inv_9", "account_id": "acct_bank"},
    )
    assert "CONFIRMATION REQUIRED" in out
    assert "PAID" in out
    # Crucially: did NOT touch the Zoho service.


def test_mark_invoice_paid_confirmed_records_payment():
    ctx = _ctx_with_entity("seo", "Pacific Edge Outsourcing LLC", "914942331")
    fake_invoice = MagicMock(
        invoice_number="INV-22", currency_code="USD", status="sent",
        balance=2993.89, total=2993.89, customer_id="C1",
    )
    fake_svc = MagicMock()
    fake_svc.get_invoice.return_value = fake_invoice
    fake_svc.record_payment.return_value = {"payment_id": "pay_1"}
    with patch("goldman.bot.tools._zoho_services_for",
                return_value=(fake_svc, MagicMock(), MagicMock(), MagicMock())):
        out = execute_tool(
            ctx=ctx, name="mark_invoice_paid",
            arguments={"entity": "seo", "invoice_id": "inv_9", "account_id": "acct_bank",
                       "amount": 2993.89, "date": "2026-06-22", "payment_mode": "Cash",
                       "reference_number": "REF123", "confirmed": True},
        )
    assert "INV-22" in out
    assert "marked paid" in out.lower()
    kwargs = fake_svc.record_payment.call_args.kwargs
    assert kwargs["amount"] == 2993.89
    assert kwargs["account_id"] == "acct_bank"
    assert kwargs["payment_mode"] == "Cash"
    assert kwargs["reference_number"] == "REF123"
    assert kwargs["customer_id"] == "C1"


def test_mark_invoice_paid_skips_already_paid_invoice():
    ctx = _ctx_with_entity("seo", "Pacific Edge Outsourcing LLC", "914942331")
    fake_invoice = MagicMock(
        invoice_number="INV-22", currency_code="USD", status="paid",
        balance=0.0, total=2993.89, customer_id="C1",
    )
    fake_svc = MagicMock()
    fake_svc.get_invoice.return_value = fake_invoice
    with patch("goldman.bot.tools._zoho_services_for",
                return_value=(fake_svc, MagicMock(), MagicMock(), MagicMock())):
        out = execute_tool(
            ctx=ctx, name="mark_invoice_paid",
            arguments={"entity": "seo", "invoice_id": "inv_9", "account_id": "acct_bank",
                       "confirmed": True},
        )
    assert "already settled" in out.lower()
    fake_svc.record_payment.assert_not_called()


def test_send_invoice_resolves_number_and_attaches_recipients():
    ctx = _ctx_with_entity("seo", "Pacific Edge Outsourcing LLC", "914942331")
    fake_svc = MagicMock()
    fake_svc.find_by_number.return_value = MagicMock(invoice_id="8399034000000260001")
    fake_svc.get_invoice.return_value = MagicMock(customer_id="C1")
    fake_svc.send_invoice.return_value = True
    fake_contact = MagicMock()
    fake_contact.get_send_recipients.return_value = {
        "contact_persons": ["cp1"], "to_mail_ids": ["gilad@example.com"],
    }
    with patch("goldman.bot.tools._zoho_services_for",
                return_value=(fake_svc, fake_contact, MagicMock(), MagicMock())):
        out = execute_tool(
            ctx=ctx, name="send_invoice",
            arguments={"entity": "seo", "invoice_id": "INV-22", "confirmed": True},
        )
    # "INV-22" is a display number → resolved to the numeric id before sending.
    fake_svc.find_by_number.assert_called_once_with("INV-22")
    fake_contact.get_send_recipients.assert_called_once_with("C1")
    args, kwargs = fake_svc.send_invoice.call_args
    assert args[0] == "8399034000000260001"
    assert kwargs["contact_persons"] == ["cp1"]
    assert kwargs["to_mail_ids"] == ["gilad@example.com"]
    assert "gilad@example.com" in out


def test_send_invoice_passes_numeric_id_without_number_lookup():
    ctx = _ctx_with_entity("seo", "Pacific Edge Outsourcing LLC", "914942331")
    fake_svc = MagicMock()
    fake_svc.get_invoice.return_value = MagicMock(customer_id="C1")
    fake_svc.send_invoice.return_value = True
    fake_contact = MagicMock()
    fake_contact.get_send_recipients.return_value = {"contact_persons": [], "to_mail_ids": ["g@x.com"]}
    with patch("goldman.bot.tools._zoho_services_for",
                return_value=(fake_svc, fake_contact, MagicMock(), MagicMock())):
        execute_tool(
            ctx=ctx, name="send_invoice",
            arguments={"entity": "seo", "invoice_id": "8399034000000260001", "confirmed": True},
        )
    fake_svc.find_by_number.assert_not_called()
    assert fake_svc.send_invoice.call_args.args[0] == "8399034000000260001"


def test_send_invoice_unknown_number_reports_not_found():
    ctx = _ctx_with_entity("seo", "Pacific Edge Outsourcing LLC", "914942331")
    fake_svc = MagicMock()
    fake_svc.find_by_number.return_value = None
    with patch("goldman.bot.tools._zoho_services_for",
                return_value=(fake_svc, MagicMock(), MagicMock(), MagicMock())):
        out = execute_tool(
            ctx=ctx, name="send_invoice",
            arguments={"entity": "seo", "invoice_id": "INV-999", "confirmed": True},
        )
    assert "no invoice matching" in out.lower()
    fake_svc.send_invoice.assert_not_called()


def test_list_customers_includes_entity_banner_no_confirmation():
    ctx = _ctx_with_entity("amzg", "AMZ-Expert Global Limited", "876247837")
    fake_svc = MagicMock()
    fake_svc.list_contacts.return_value = [
        MagicMock(contact_id="C1", contact_name="MOYOU", email="x@y.com"),
    ]
    with patch("goldman.bot.tools._zoho_services_for",
                return_value=(MagicMock(), fake_svc, MagicMock(), MagicMock())):
        out = execute_tool(
            ctx=ctx, name="list_customers",
            arguments={"entity": "amzg"},
        )
    assert "AMZ-Expert Global Limited" in out
    assert "876247837" in out
    assert "MOYOU" in out


def test_zoho_call_with_no_entity_is_refused():
    ctx = MagicMock()
    ctx.conn = MagicMock()
    cur = ctx.conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = None  # entity slug not found
    out = execute_tool(
        ctx=ctx, name="list_customers", arguments={"entity": "bogus"},
    )
    assert "refused" in out.lower()
    assert "amz-expert global" in out.lower()
    assert "pacific edge" in out.lower()


def test_confirmation_prompt_flags_new_vendor_by_name():
    info = EntityInfo(slug="amzg",
                       legal_name="AMZ-Expert Global Limited",
                       org_id="876247837")
    prompt = confirmation_prompt(info, "create_expense", {
        "amount": 5900, "currency": "ILS", "vendor_name": "Bezeq",
        "description": "Utility bill",
    })
    assert "Bezeq" in prompt
    assert "NEW" in prompt


def test_confirmation_prompt_shows_known_vendor_id_unchanged():
    info = EntityInfo(slug="amzg",
                       legal_name="AMZ-Expert Global Limited",
                       org_id="876247837")
    prompt = confirmation_prompt(info, "create_expense", {
        "amount": 5900, "currency": "ILS", "vendor_id": "V-1",
    })
    assert "vendor=V-1" in prompt
