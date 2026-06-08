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


def build_who_view(
    *,
    entities_repo,
    tax_repo,
    bank_repo,
    clients_repo,
    vendors_repo,
    top_n: int = 5,
) -> list:
    """Build a list of EntitySummary objects, parent-first ordering."""
    result = []
    for ent in entities_repo.list_all():
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

    return "\n".join(lines).lstrip("\n")
