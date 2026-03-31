"""Zoho Books Contact service — list and search customers."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from zoho.client import ZohoClient

logger = logging.getLogger(__name__)


@dataclass
class Contact:
    contact_id: str
    contact_name: str
    company_name: str
    email: str


class ContactService:
    def __init__(self, client: ZohoClient):
        self.client = client
        self._cache: dict[str, str] = {}  # name (lower) -> contact_id

    def list_contacts(self, page: int = 1, per_page: int = 200) -> list[Contact]:
        data = self.client.get(
            "contacts", params={"page": page, "per_page": per_page}
        )
        contacts = []
        for raw in data.get("contacts", []):
            c = Contact(
                contact_id=raw.get("contact_id", ""),
                contact_name=raw.get("contact_name", ""),
                company_name=raw.get("company_name", ""),
                email=raw.get("email", ""),
            )
            contacts.append(c)
            self._cache[c.contact_name.lower()] = c.contact_id
        return contacts

    def search_by_name(self, name: str) -> Contact | None:
        data = self.client.get(
            "contacts", params={"contact_name": name}
        )
        results = data.get("contacts", [])
        if not results:
            return None
        raw = results[0]
        return Contact(
            contact_id=raw.get("contact_id", ""),
            contact_name=raw.get("contact_name", ""),
            company_name=raw.get("company_name", ""),
            email=raw.get("email", ""),
        )

    def get_customer_id(self, name: str) -> str:
        """Resolve a customer name to a contact_id, with caching."""
        key = name.lower()
        if key in self._cache:
            return self._cache[key]

        contact = self.search_by_name(name)
        if contact:
            self._cache[key] = contact.contact_id
            return contact.contact_id

        raise ValueError(f"Customer not found: {name}")

    def create_contact(
        self,
        contact_name: str,
        company_name: str = "",
        email: str = "",
        phone: str = "",
        contact_type: str = "customer",
    ) -> Contact:
        """Create a new contact in Zoho Books."""
        payload: dict = {"contact_name": contact_name, "contact_type": contact_type}
        if company_name:
            payload["company_name"] = company_name
        if email or phone:
            person: dict = {}
            if email:
                person["email"] = email
            if phone:
                person["phone"] = phone
            payload["contact_persons"] = [person]

        data = self.client.post("contacts", json=payload)
        raw = data.get("contact", {})
        c = Contact(
            contact_id=raw.get("contact_id", ""),
            contact_name=raw.get("contact_name", contact_name),
            company_name=raw.get("company_name", company_name),
            email=raw.get("email", email),
        )
        self._cache[c.contact_name.lower()] = c.contact_id
        logger.info("Created contact %s (%s)", c.contact_name, c.contact_id)
        return c
