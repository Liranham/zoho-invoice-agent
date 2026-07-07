"""Phase 9 — Zoho safety guardrails.

Prevents Goldman from accidentally acting on the wrong Zoho Books
organization (e.g. creating a Pacific Edge invoice in AMZ-Expert Global,
or vice versa). Five layers, all routed through this module:

1. Entity resolution — every Zoho call must resolve to a known
   (slug, legal_name, org_id) triple; refuses otherwise.
2. Entity banner — every Zoho tool result is prefixed with
   `[ENTITY: <legal_name> | Zoho org <id>]`.
3. Two-phase confirmation — write tools (create_invoice, create_expense,
   create_customer, send_invoice) refuse to execute until `confirmed: true`
   is passed in arguments, returning a confirmation prompt instead.
4. Ambiguity refusal — the persona instructs Claude to refuse Zoho actions
   that don't unambiguously name a company.
5. Audit log — every call (executed or blocked) lands in
   goldman.zoho_audit with full args, status, and result summary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional


WRITE_TOOLS = {
    "create_invoice",
    "create_expense",
    "create_customer",
    "send_invoice",
    "mark_invoice_paid",
}

READ_TOOLS = {
    "list_invoices",
    "list_customers",
    "list_vendors",
    "list_pending_confirmations",
}

ALL_ZOHO_TOOLS = WRITE_TOOLS | READ_TOOLS


@dataclass(frozen=True)
class EntityInfo:
    slug: str
    legal_name: str
    org_id: str


class UnknownEntityError(RuntimeError):
    pass


def resolve_entity(conn, slug: str) -> EntityInfo:
    """Look up an entity. Raises UnknownEntityError if the slug is bogus
    or there's no Zoho organization wired for it yet."""
    if not slug:
        raise UnknownEntityError("entity slug is required")
    s = slug.strip().lower()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT slug, legal_name, zoho_organization_id "
            "FROM goldman.entities WHERE slug = %s",
            (s,),
        )
        row = cur.fetchone()
    if not row:
        raise UnknownEntityError(f"no entity {slug!r}")
    if not row[2]:
        raise UnknownEntityError(
            f"entity {row[1]!r} ({s}) has no Zoho organization wired up yet"
        )
    return EntityInfo(slug=row[0], legal_name=row[1], org_id=row[2])


def banner(info: EntityInfo) -> str:
    """The mandatory prefix shown on every Zoho tool reply."""
    return f"[ENTITY: {info.legal_name} ({info.slug}) | Zoho org {info.org_id}]"


def needs_confirmation(tool_name: str, args: dict) -> bool:
    """True when a WRITE tool is invoked without an explicit confirm."""
    if tool_name not in WRITE_TOOLS:
        return False
    return not args.get("confirmed", False)


def confirmation_prompt(info: EntityInfo, tool_name: str, args: dict) -> str:
    """Human-readable confirmation requested before a write executes."""
    desc = _describe_action(tool_name, args)
    return (
        f"{banner(info)}\n"
        f"⚠️  CONFIRMATION REQUIRED — about to {desc}\n"
        f"   Company: {info.legal_name}\n"
        f"   Zoho org: {info.org_id}\n\n"
        f"If everything above is correct, re-issue the same tool call with "
        f"argument `confirmed: true`. Otherwise reply with what's wrong "
        f"(wrong company / wrong amount / wrong customer / abort)."
    )


def _describe_action(tool_name: str, args: dict) -> str:
    if tool_name == "create_invoice":
        line_items = args.get("line_items")
        if line_items:
            try:
                total = sum(
                    float(li.get("rate", li.get("amount", 0)) or 0)
                    * float(li.get("quantity", 1) or 1)
                    for li in line_items
                )
            except (TypeError, ValueError):
                total = "?"
            return (
                f"CREATE INVOICE for customer_id={args.get('customer_id', '?')}, "
                f"{len(line_items)} line(s), total={total}"
            )
        return (
            f"CREATE INVOICE for customer_id={args.get('customer_id', '?')}, "
            f"amount={args.get('amount', '?')}, "
            f"description={args.get('description', '?')!r}"
        )
    if tool_name == "mark_invoice_paid":
        return (
            f"RECORD PAYMENT marking invoice {args.get('invoice_id', '?')} PAID "
            f"(amount={args.get('amount', 'full balance')}, "
            f"mode={args.get('payment_mode', 'banktransfer')}, "
            f"deposit_account={args.get('account_id', '?')})"
        )
    if tool_name == "create_expense":
        return (
            f"CREATE EXPENSE for {args.get('amount', '?')} "
            f"{args.get('currency', 'USD')}, vendor={args.get('vendor_id', '?')}, "
            f"description={args.get('description', '?')!r}"
        )
    if tool_name == "create_customer":
        return (
            f"CREATE CUSTOMER name={args.get('name', '?')!r}, "
            f"company={args.get('company', '')!r}, "
            f"email={args.get('email', '')!r}"
        )
    if tool_name == "send_invoice":
        return f"EMAIL invoice {args.get('invoice_id', '?')} to its customer"
    return f"perform {tool_name}"


def log_audit(
    conn,
    *,
    info: EntityInfo,
    tool_name: str,
    arguments: dict,
    status: str,
    result_summary: str = "",
    channel_id: str = "",
) -> None:
    """Insert a row into goldman.zoho_audit. Best effort: failures don't
    block the tool result."""
    safe_args = _scrub_args(arguments)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.zoho_audit
                    (entity_slug, entity_legal_name, zoho_organization_id,
                     tool_name, arguments, status, result_summary, channel_id)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                """,
                (
                    info.slug, info.legal_name, info.org_id,
                    tool_name, json.dumps(safe_args, default=str),
                    status, result_summary[:500] if result_summary else None,
                    channel_id or None,
                ),
            )
    except Exception:
        pass


def log_blocked_no_entity(
    conn, *, tool_name: str, arguments: dict,
    reason: str, channel_id: str = "",
) -> None:
    """Audit a call that couldn't even resolve an entity (ambiguous /
    missing / unknown). Used when resolve_entity fails."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO goldman.zoho_audit
                    (entity_slug, entity_legal_name, zoho_organization_id,
                     tool_name, arguments, status, result_summary, channel_id)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                """,
                (
                    arguments.get("entity") or "(none)",
                    "(unresolved)", "(unresolved)",
                    tool_name, json.dumps(_scrub_args(arguments), default=str),
                    "blocked_ambiguous", reason[:500],
                    channel_id or None,
                ),
            )
    except Exception:
        pass


def _scrub_args(arguments: dict) -> dict:
    """Light scrub for the audit log — keep the arg names but truncate
    anything excessively long. Zoho calls don't carry secrets, but body
    fields can be long descriptions."""
    out = {}
    for k, v in (arguments or {}).items():
        if isinstance(v, str) and len(v) > 1000:
            out[k] = v[:1000] + "…(truncated)"
        else:
            out[k] = v
    return out
