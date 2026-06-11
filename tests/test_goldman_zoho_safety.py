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
