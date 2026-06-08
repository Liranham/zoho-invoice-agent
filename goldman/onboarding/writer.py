"""Writes extracted onboarding data into the goldman.* tables."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional
from uuid import UUID


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


@dataclass
class WriteSummary:
    tax_registrations_inserted: int = 0
    bank_accounts_upserted: int = 0
    vendors_upserted: int = 0
    clients_upserted: int = 0
    facts_upserted: int = 0
    metadata_updated: bool = False


class OnboardingWriter:
    def __init__(
        self,
        *,
        entities_repo,
        tax_repo,
        clients_repo,
        vendors_repo,
        bank_repo,
        facts_repo,
    ):
        self.entities_repo = entities_repo
        self.tax_repo = tax_repo
        self.clients_repo = clients_repo
        self.vendors_repo = vendors_repo
        self.bank_repo = bank_repo
        self.facts_repo = facts_repo

    def write(
        self,
        *,
        entity_slug: str,
        entity_id: UUID,
        extraction: dict,
    ) -> WriteSummary:
        s = WriteSummary()

        for tr in extraction.get("tax_registrations", []):
            self.tax_repo.insert(
                entity_id=entity_id,
                tax_type=tr["tax_type"],
                jurisdiction=tr["jurisdiction"],
                registration_number=tr.get("registration_number"),
                effective_from=_parse_date(tr.get("effective_from")),
                effective_to=_parse_date(tr.get("effective_to")),
                filing_cadence=tr.get("filing_cadence"),
                notes=tr.get("notes"),
                source="extracted",
            )
            s.tax_registrations_inserted += 1

        for ba in extraction.get("bank_accounts", []):
            self.bank_repo.upsert_by_label(
                entity_id=entity_id,
                provider=ba["provider"],
                account_label=ba["account_label"],
                currency=ba["currency"],
                account_identifier=ba.get("account_identifier"),
                notes=ba.get("notes"),
            )
            s.bank_accounts_upserted += 1

        for v in extraction.get("vendors", []):
            self.vendors_repo.upsert_by_name(
                entity_id=entity_id,
                vendor_name=v["vendor_name"],
                email_domain=v.get("email_domain"),
                category=v.get("category"),
                typical_amount=v.get("typical_amount"),
                typical_currency=v.get("typical_currency"),
                typical_cadence=v.get("typical_cadence"),
            )
            s.vendors_upserted += 1

        for c in extraction.get("clients", []):
            # Clients without a zoho_contact_id can't be upserted by zoho id;
            # the Zoho sync pass fills those in later. For brain-dump-only
            # clients, we synthesise a placeholder id keyed on the name.
            self.clients_repo.upsert_by_zoho_id(
                entity_id=entity_id,
                zoho_contact_id=f"manual:{c['contact_name'].lower()}",
                contact_name=c["contact_name"],
                company_name=c.get("company_name"),
                primary_email=c.get("primary_email"),
            )
            s.clients_upserted += 1

        for f in extraction.get("facts", []):
            self.facts_repo.upsert(
                entity_id=entity_id,
                kind=f["kind"],
                fact=f["fact"],
                source="extracted",
            )
            s.facts_upserted += 1

        meta = extraction.get("entity_metadata", {}) or {}
        if any(meta.values()):
            self.entities_repo.update_metadata(
                entity_slug,
                fiscal_year_end=meta.get("fiscal_year_end"),
                registered_address=meta.get("registered_address"),
                company_number=meta.get("company_number"),
                incorporation_date=_parse_date(meta.get("incorporation_date")),
            )
            s.metadata_updated = True

        return s
