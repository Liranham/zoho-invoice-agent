"""Sync Zoho contacts into goldman.clients + goldman.vendors."""

from __future__ import annotations

from typing import Callable
from uuid import UUID


def _email_domain(email: str) -> str:
    if not email or "@" not in email:
        return ""
    return email.split("@", 1)[1].lower()


def sync_zoho_contacts(
    *,
    contact_service,
    entity_id: UUID,
    clients_repo,
    vendors_repo,
    is_vendor: Callable[[object], bool],
    page_limit: int = 5,
) -> dict:
    """Iterate Zoho contacts (paged), route to clients or vendors.

    `is_vendor(contact)` returns True if the contact should be treated as a
    vendor. For Phase 1 the default routing (set by the CLI command) is by
    the Zoho contact_type field: 'vendor' → vendors, anything else → clients.
    """
    summary = {"clients": 0, "vendors": 0}
    for page in range(1, page_limit + 1):
        contacts = contact_service.list_contacts(page=page)
        if not contacts:
            break
        for c in contacts:
            if is_vendor(c):
                vendors_repo.upsert_by_name(
                    entity_id=entity_id,
                    vendor_name=c.contact_name,
                    zoho_contact_id=c.contact_id,
                    email_domain=_email_domain(c.email),
                )
                summary["vendors"] += 1
            else:
                clients_repo.upsert_by_zoho_id(
                    entity_id=entity_id,
                    zoho_contact_id=c.contact_id,
                    contact_name=c.contact_name,
                    company_name=c.company_name,
                    primary_email=c.email,
                )
                summary["clients"] += 1
    return summary
