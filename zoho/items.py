"""Zoho Books Item service — list and search items/products."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from zoho.client import ZohoClient

logger = logging.getLogger(__name__)


@dataclass
class Item:
    item_id: str
    name: str
    rate: float
    description: str


class ItemService:
    def __init__(self, client: ZohoClient):
        self.client = client
        self._cache: dict[str, str] = {}  # name (lower) -> item_id

    def list_items(self, page: int = 1, per_page: int = 200) -> list[Item]:
        data = self.client.get("items", params={"page": page, "per_page": per_page})
        items = []
        for raw in data.get("items", []):
            item = Item(
                item_id=raw.get("item_id", ""),
                name=raw.get("name", ""),
                rate=float(raw.get("rate", 0)),
                description=raw.get("description", ""),
            )
            items.append(item)
            self._cache[item.name.lower()] = item.item_id
        return items

    def get_item_id(self, name: str) -> str:
        """Resolve an item name to an item_id, with caching."""
        key = name.lower()
        if key in self._cache:
            return self._cache[key]

        # Search API
        data = self.client.get("items", params={"name": name})
        results = data.get("items", [])
        if results:
            item_id = results[0].get("item_id", "")
            self._cache[key] = item_id
            return item_id

        raise ValueError(f"Item not found: {name}")
