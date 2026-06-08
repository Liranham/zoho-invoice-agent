"""Tests for the Zoho contacts sync."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from goldman.sync.zoho_contacts import sync_zoho_contacts


def test_sync_routes_customers_to_clients_repo():
    fake_client = MagicMock()
    contact = MagicMock()
    contact.contact_id = "zoho_c_123"
    contact.contact_name = "Acme"
    contact.company_name = "Acme Inc"
    contact.email = "ops@acme.com"
    # First page returns the contact; subsequent pages return empty -> loop exits
    fake_client.list_contacts.side_effect = [[contact], []]

    clients_repo = MagicMock()
    vendors_repo = MagicMock()
    eid = uuid4()

    result = sync_zoho_contacts(
        contact_service=fake_client,
        entity_id=eid,
        clients_repo=clients_repo,
        vendors_repo=vendors_repo,
        is_vendor=lambda c: False,   # treat all as clients
    )

    clients_repo.upsert_by_zoho_id.assert_called_once()
    kwargs = clients_repo.upsert_by_zoho_id.call_args.kwargs
    assert kwargs["zoho_contact_id"] == "zoho_c_123"
    assert kwargs["entity_id"] == eid
    assert result["clients"] == 1
    assert result["vendors"] == 0


def test_sync_routes_vendors_to_vendors_repo():
    fake_client = MagicMock()
    contact = MagicMock()
    contact.contact_id = "zoho_v_999"
    contact.contact_name = "Helium 10"
    contact.company_name = "Helium 10"
    contact.email = "billing@helium10.com"
    fake_client.list_contacts.side_effect = [[contact], []]

    clients_repo = MagicMock()
    vendors_repo = MagicMock()
    eid = uuid4()

    result = sync_zoho_contacts(
        contact_service=fake_client,
        entity_id=eid,
        clients_repo=clients_repo,
        vendors_repo=vendors_repo,
        is_vendor=lambda c: True,
    )

    vendors_repo.upsert_by_name.assert_called_once()
    kwargs = vendors_repo.upsert_by_name.call_args.kwargs
    assert kwargs["entity_id"] == eid
    assert kwargs["vendor_name"] == "Helium 10"
    assert kwargs["zoho_contact_id"] == "zoho_v_999"
    assert kwargs["email_domain"] == "helium10.com"
    assert result["vendors"] == 1
