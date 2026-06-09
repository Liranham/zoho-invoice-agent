"""Composable 'who' view of the Goldman company tree.

Build-and-render split: build_who_view returns structured data that
Telegram bot + Claude Code plugin can both consume; render_who is the
plain-text rendering used by CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from uuid import UUID

from goldman.cross_entity import intercompany_flow, last_tp_doc


@dataclass
class EntitySummary:
    id: UUID
    slug: str
    legal_name: str
    jurisdiction: str
    parent_entity_id: Optional[UUID]
    base_currency: str
    fiscal_year_end: Optional[str]
    registered_address: Optional[str]
    company_number: Optional[str]
    incorporation_date: Optional[date]
    tax_registrations: list = field(default_factory=list)
    bank_accounts: list = field(default_factory=list)
    top_clients: list = field(default_factory=list)
    top_vendors: list = field(default_factory=list)
    # Phase 6.4 cross-entity fields
    intercompany_flow: dict = field(default_factory=lambda: {
        "count": 0, "total": 0.0, "currency": None, "counterpart": None,
    })
    last_tp_doc: Optional[dict] = None


def build_who_view(
    *,
    entities_repo,
    tax_repo,
    bank_repo,
    clients_repo,
    vendors_repo,
    conn=None,
    top_n: int = 5,
) -> list:
    """Build a list of EntitySummary objects, parent-first ordering.

    `conn` is required to populate cross-entity fields (intercompany_flow,
    last_tp_doc). When None, those fields stay at their defaults.
    """
    all_entities = entities_repo.list_all()

    result = []
    for ent in all_entities:
        ic_flow = {"count": 0, "total": 0.0, "currency": None, "counterpart": None}
        tp_doc = None
        if conn is not None:
            counterparts = [e for e in all_entities if e.id != ent.id]
            running = {"count": 0, "total": 0.0, "currencies": set(),
                       "counterpart_label": None}
            for cp in counterparts:
                flow = intercompany_flow(
                    conn=conn,
                    entity_a_id=ent.id,
                    entity_b_legal_name=cp.legal_name,
                )
                if flow["count"] > 0:
                    running["count"] += flow["count"]
                    running["total"] += flow["total"]
                    if flow["currency"] is not None:
                        running["currencies"].add(flow["currency"])
                    running["counterpart_label"] = cp.legal_name
            if running["count"] > 0:
                if len(running["currencies"]) == 1:
                    cur = running["currencies"].pop()
                else:
                    cur = "mixed"
                ic_flow = {
                    "count": running["count"],
                    "total": running["total"],
                    "currency": cur,
                    "counterpart": running["counterpart_label"],
                }
            if counterparts:
                tp_doc = last_tp_doc(
                    conn=conn,
                    entity_a_legal_name=ent.legal_name,
                    entity_b_legal_name=counterparts[0].legal_name,
                )

        s = EntitySummary(
            id=ent.id, slug=ent.slug,
            legal_name=ent.legal_name,
            jurisdiction=ent.jurisdiction,
            parent_entity_id=ent.parent_entity_id,
            base_currency=ent.base_currency,
            fiscal_year_end=getattr(ent, "fiscal_year_end", None),
            registered_address=getattr(ent, "registered_address", None),
            company_number=getattr(ent, "company_number", None),
            incorporation_date=getattr(ent, "incorporation_date", None),
            tax_registrations=tax_repo.list_live(ent.id),
            bank_accounts=bank_repo.list_by_entity(ent.id),
            top_clients=clients_repo.list_by_entity(ent.id)[:top_n],
            top_vendors=vendors_repo.list_by_entity(ent.id)[:top_n],
            intercompany_flow=ic_flow,
            last_tp_doc=tp_doc,
        )
        result.append(s)
    return result


def render_who(summaries) -> str:
    """Render summaries as plain text, parent-first then children."""
    lines = []
    for s in summaries:
        prefix = "  -> " if s.parent_entity_id else ""
        lines.append(f"\n{prefix}{s.legal_name} ({s.slug})")
        lines.append(f"   Jurisdiction:     {s.jurisdiction}")
        lines.append(f"   Base currency:    {s.base_currency}")
        lines.append(f"   Fiscal year end:  {s.fiscal_year_end or '-- missing --'}")
        lines.append(f"   Registered addr:  {s.registered_address or '-- missing --'}")
        lines.append(f"   Company number:   {s.company_number or '-- missing --'}")

        lines.append("   Tax registrations:")
        if s.tax_registrations:
            for tr in s.tax_registrations:
                regn = tr.registration_number or "(no number)"
                cad = tr.filing_cadence or "(no cadence)"
                lines.append(f"     - {tr.tax_type} / {tr.jurisdiction} - {regn} [{cad}]")
        else:
            lines.append("     (none)")

        lines.append("   Bank accounts:")
        if s.bank_accounts:
            for ba in s.bank_accounts:
                lines.append(f"     - {ba.provider} - {ba.account_label} ({ba.currency})")
        else:
            lines.append("     (none)")

        lines.append(f"   Top clients ({len(s.top_clients)}):")
        for c in s.top_clients:
            tier = f" [tier {c.tier}]" if c.tier else ""
            lines.append(f"     - {c.contact_name}{tier}")

        lines.append(f"   Top vendors ({len(s.top_vendors)}):")
        for v in s.top_vendors:
            cat = f" - {v.category}" if v.category else ""
            lines.append(f"     - {v.vendor_name}{cat}")

        # Phase 6.4: intercompany flow (last 30 days)
        flow = s.intercompany_flow or {}
        lines.append("   Intercompany flow (30d):")
        if flow.get("count", 0) > 0:
            cur = flow.get("currency") or ""
            cp = flow.get("counterpart") or "(unknown)"
            total = flow.get("total", 0.0)
            lines.append(
                f"     -> {cp}: {total:,.2f} {cur} across "
                f"{flow['count']} bill{'s' if flow['count'] != 1 else ''}"
            )
        else:
            lines.append("     (none)")

        # Phase 6.4: last TP doc on file
        tp = s.last_tp_doc
        lines.append("   TP documentation:")
        if tp:
            label = (
                f"{tp['source']}: {tp.get('pack_version') or tp['filename']}"
                if tp["source"] == "knowledge_pack"
                else tp["filename"]
            )
            uploaded = tp.get("uploaded_at") or ""
            short_date = uploaded[:10] if uploaded else "(unknown date)"
            lines.append(f"     {label} (uploaded {short_date})")
        else:
            lines.append("     (no TP documentation on file)")

    return "\n".join(lines).lstrip("\n")
