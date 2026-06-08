"""Supabase Storage HTTP client (service-role; bypasses RLS).

Used only by Goldman code. Reads GOLDMAN_SUPABASE_URL and
GOLDMAN_SUPABASE_SERVICE_KEY from env.
"""

from __future__ import annotations

import os

import requests


class StorageConfigError(RuntimeError):
    pass


class SupabaseStorage:
    def __init__(self):
        url = os.getenv("GOLDMAN_SUPABASE_URL", "")
        key = os.getenv("GOLDMAN_SUPABASE_SERVICE_KEY", "")
        if not url or not key:
            raise StorageConfigError(
                "GOLDMAN_SUPABASE_URL and GOLDMAN_SUPABASE_SERVICE_KEY required."
            )
        self.base_url = url.rstrip("/")
        self.service_key = key

    def _url(self, bucket: str, path: str) -> str:
        path = path.lstrip("/")
        return f"{self.base_url}/storage/v1/object/{bucket}/{path}"

    def upload(self, *, bucket: str, path: str, content: bytes, content_type: str) -> None:
        url = self._url(bucket, path)
        resp = requests.put(
            url,
            data=content,
            headers={
                "Authorization": f"Bearer {self.service_key}",
                "Content-Type": content_type,
                "x-upsert": "true",
            },
            timeout=60,
        )
        resp.raise_for_status()

    def download(self, *, bucket: str, path: str) -> bytes:
        url = self._url(bucket, path)
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {self.service_key}"},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.content
