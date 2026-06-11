"""Per-entity Zoho client factory.

Every Goldman operation routes through here. The factory:
  * Looks up the entity in goldman.entities.
  * Resolves env-var credentials by zoho_credential_key (e.g. ZOHO_AMZG_*).
  * Caches one ZohoClient per slug per process.

The shape mirrors the spec §5.3 — no global default Zoho ever again.
"""

from __future__ import annotations

import os
from typing import Optional

from auth.zoho_auth import ZohoAuth
from goldman_db.entities import EntityRepository
from zoho.client import ZohoClient
from zoho.contacts import ContactService
from zoho.expenses import ExpenseService
from zoho.invoices import InvoiceService
from zoho.items import ItemService


class GoldmanZohoError(Exception):
    """Base class for Goldman Zoho factory errors."""


class UnknownEntityError(GoldmanZohoError):
    """Raised when a slug doesn't match any row in goldman.entities."""


class MissingZohoCredentialsError(GoldmanZohoError):
    """Raised when an entity's Zoho env vars are not configured."""


_client_cache: dict[str, ZohoClient] = {}


def _env(key: str) -> str:
    return os.getenv(key, "")


def _resolve_credentials(cred_key: str) -> tuple[str, str, str, str, str]:
    """Return (client_id, client_secret, refresh_token, accounts_url, api_base_url)
    for the given credential key prefix (e.g. "AMZG" → ZOHO_AMZG_*)."""
    prefix = cred_key.upper()
    client_id = _env(f"ZOHO_{prefix}_CLIENT_ID")
    client_secret = _env(f"ZOHO_{prefix}_CLIENT_SECRET")
    refresh_token = _env(f"ZOHO_{prefix}_REFRESH_TOKEN")
    accounts_url = _env(f"ZOHO_{prefix}_ACCOUNTS_URL") or "https://accounts.zoho.com"
    api_base_url = _env(f"ZOHO_{prefix}_API_BASE_URL") or "https://www.zohoapis.com/books/v3"

    missing = [
        name for name, val in [
            (f"ZOHO_{prefix}_CLIENT_ID", client_id),
            (f"ZOHO_{prefix}_CLIENT_SECRET", client_secret),
            (f"ZOHO_{prefix}_REFRESH_TOKEN", refresh_token),
        ] if not val
    ]
    if missing:
        raise MissingZohoCredentialsError(
            f"Missing env vars for entity credential key {prefix!r}: "
            f"{', '.join(missing)}"
        )
    return client_id, client_secret, refresh_token, accounts_url, api_base_url


def _default_entity_repo() -> EntityRepository:
    """Build an EntityRepository from a fresh app DB connection.

    Phase 0 callers always pass entity_repo explicitly; this hook lands
    in Phase 1 alongside the conversational interface.
    """
    raise NotImplementedError(
        "for_entity() requires an entity_repo argument in v0; "
        "DB-backed default will land alongside Phase 1."
    )


def for_entity(
    slug: str,
    *,
    entity_repo: Optional[EntityRepository] = None,
) -> ZohoClient:
    """Return a cached ZohoClient for the given entity slug.

    Raises UnknownEntityError if no entity with that slug exists,
    or MissingZohoCredentialsError if env vars aren't set.
    """
    normalised = slug.lower()

    if normalised in _client_cache:
        return _client_cache[normalised]

    repo = entity_repo or _default_entity_repo()
    entity = repo.get_by_slug(normalised)
    if entity is None:
        raise UnknownEntityError(f"No goldman.entities row with slug {slug!r}")

    if not entity.zoho_credential_key:
        raise MissingZohoCredentialsError(
            f"Entity {slug!r} has no zoho_credential_key set"
        )
    if not entity.zoho_organization_id:
        raise MissingZohoCredentialsError(
            f"Entity {slug!r} has no zoho_organization_id set"
        )

    (
        client_id, client_secret, refresh_token,
        accounts_url, api_base_url,
    ) = _resolve_credentials(entity.zoho_credential_key)

    auth = ZohoAuth(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        accounts_url=accounts_url,
    )
    client = ZohoClient(auth, api_base_url, entity.zoho_organization_id)
    _client_cache[normalised] = client
    return client


def invoice_service_for(
    slug: str,
    *,
    entity_repo: Optional[EntityRepository] = None,
) -> InvoiceService:
    return InvoiceService(for_entity(slug, entity_repo=entity_repo))


def contact_service_for(
    slug: str,
    *,
    entity_repo: Optional[EntityRepository] = None,
) -> ContactService:
    return ContactService(for_entity(slug, entity_repo=entity_repo))


def item_service_for(
    slug: str,
    *,
    entity_repo: Optional[EntityRepository] = None,
) -> ItemService:
    return ItemService(for_entity(slug, entity_repo=entity_repo))


def expense_service_for(
    slug: str,
    *,
    entity_repo: Optional[EntityRepository] = None,
) -> ExpenseService:
    return ExpenseService(for_entity(slug, entity_repo=entity_repo))
