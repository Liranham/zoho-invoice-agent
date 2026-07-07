"""Tests for ContactService — contact_type filtering + field."""

from __future__ import annotations

from unittest.mock import MagicMock

from zoho.contacts import Contact, ContactService


def test_list_contacts_passes_contact_type_filter():
    client = MagicMock()
    client.get.return_value = {"contacts": []}

    svc = ContactService(client)
    svc.list_contacts(contact_type="vendor")

    client.get.assert_called_once_with(
        "contacts", params={"page": 1, "per_page": 200, "contact_type": "vendor"},
    )


def test_list_contacts_omits_filter_by_default():
    client = MagicMock()
    client.get.return_value = {"contacts": []}

    svc = ContactService(client)
    svc.list_contacts()

    client.get.assert_called_once_with(
        "contacts", params={"page": 1, "per_page": 200},
    )


def test_list_contacts_populates_contact_type_field():
    client = MagicMock()
    client.get.return_value = {
        "contacts": [
            {"contact_id": "V-1", "contact_name": "Akiva CPA",
             "company_name": "", "email": "", "contact_type": "vendor"},
        ],
    }

    svc = ContactService(client)
    contacts = svc.list_contacts(contact_type="vendor")

    assert contacts[0].contact_type == "vendor"


def test_create_contact_creates_vendor_type():
    client = MagicMock()
    client.post.return_value = {
        "contact": {"contact_id": "V-2", "contact_name": "Bezeq",
                    "company_name": "", "email": "", "contact_type": "vendor"},
    }

    svc = ContactService(client)
    contact = svc.create_contact(contact_name="Bezeq", contact_type="vendor")

    assert isinstance(contact, Contact)
    assert contact.contact_type == "vendor"
    _, kwargs = client.post.call_args
    assert kwargs["json"]["contact_type"] == "vendor"
