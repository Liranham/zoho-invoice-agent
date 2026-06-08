"""Tests for the per-entity Zoho factory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from goldman.zoho import (
    UnknownEntityError,
    MissingZohoCredentialsError,
    for_entity,
    invoice_service_for,
    contact_service_for,
    item_service_for,
)


@pytest.fixture(autouse=True)
def reset_factory_cache():
    """Clear the factory's per-process cache between tests."""
    from goldman.zoho import _client_cache
    _client_cache.clear()
    yield
    _client_cache.clear()


def _entity_repo_with(slug, cred_key, org_id):
    """Build a fake EntityRepository returning one entity."""
    from goldman_db.entities import Entity
    fake = MagicMock()
    fake.get_by_slug.return_value = Entity(
        id=uuid4(),
        slug=slug,
        legal_name=f"Test {slug.upper()}",
        jurisdiction="HK",
        parent_entity_id=None,
        base_currency="USD",
        zoho_organization_id=org_id,
        zoho_credential_key=cred_key,
        fiscal_year_end=None,
        registered_address=None,
        company_number=None,
        incorporation_date=None,
    )
    return fake


def test_for_entity_returns_zoho_client(monkeypatch):
    monkeypatch.setenv("ZOHO_TEST_CLIENT_ID", "cid_test")
    monkeypatch.setenv("ZOHO_TEST_CLIENT_SECRET", "secret_test")
    monkeypatch.setenv("ZOHO_TEST_REFRESH_TOKEN", "refresh_test")

    repo = _entity_repo_with("amzg", "TEST", "org_42")

    client = for_entity("amzg", entity_repo=repo)

    assert client.organization_id == "org_42"
    assert client.auth.client_id == "cid_test"
    assert client.auth.refresh_token == "refresh_test"


def test_for_entity_caches_clients_per_slug(monkeypatch):
    monkeypatch.setenv("ZOHO_TEST_CLIENT_ID", "cid")
    monkeypatch.setenv("ZOHO_TEST_CLIENT_SECRET", "sec")
    monkeypatch.setenv("ZOHO_TEST_REFRESH_TOKEN", "rt")

    repo = _entity_repo_with("amzg", "TEST", "org_1")

    first = for_entity("amzg", entity_repo=repo)
    second = for_entity("amzg", entity_repo=repo)

    assert first is second  # cached


def test_for_entity_raises_for_unknown_slug():
    repo = MagicMock()
    repo.get_by_slug.return_value = None

    with pytest.raises(UnknownEntityError, match="nope"):
        for_entity("nope", entity_repo=repo)


def test_for_entity_raises_when_credentials_missing(monkeypatch):
    # Ensure env vars are NOT set
    monkeypatch.delenv("ZOHO_MISSING_CLIENT_ID", raising=False)
    monkeypatch.delenv("ZOHO_MISSING_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("ZOHO_MISSING_REFRESH_TOKEN", raising=False)

    repo = _entity_repo_with("amzg", "MISSING", "org_1")

    with pytest.raises(MissingZohoCredentialsError, match="MISSING"):
        for_entity("amzg", entity_repo=repo)


def test_invoice_service_for_returns_invoice_service(monkeypatch):
    monkeypatch.setenv("ZOHO_TEST_CLIENT_ID", "cid")
    monkeypatch.setenv("ZOHO_TEST_CLIENT_SECRET", "sec")
    monkeypatch.setenv("ZOHO_TEST_REFRESH_TOKEN", "rt")

    repo = _entity_repo_with("amzg", "TEST", "org_1")

    svc = invoice_service_for("amzg", entity_repo=repo)

    from zoho.invoices import InvoiceService
    assert isinstance(svc, InvoiceService)
