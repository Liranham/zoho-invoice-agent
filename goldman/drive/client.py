"""Google Drive REST client for Goldman.

Reuses Liran's personal Google OAuth (same scope structure as Bob).
Credentials + token are base64-encoded in env per the existing Gmail pattern.
"""

from __future__ import annotations

import base64
import io
import os
import pickle

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload


SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class DriveConfigError(RuntimeError):
    pass


def _load_creds():
    token_b64 = os.getenv("GOLDMAN_DRIVE_TOKEN_B64", "")
    if not token_b64:
        raise DriveConfigError(
            "GOLDMAN_DRIVE_TOKEN_B64 not set. Provide a base64'd google-auth "
            "Credentials object pickled (same pattern as Bob's GOOGLE_TOKEN_B64)."
        )
    return pickle.loads(base64.b64decode(token_b64))


class GoogleDriveClient:
    def __init__(self):
        creds = _load_creds()
        self._service = build("drive", "v3", credentials=creds,
                              cache_discovery=False)

    def find_folder(self, *, name: str, parent_id):
        """Return the folder id matching (name, parent_id), or None."""
        q = (
            f"mimeType = 'application/vnd.google-apps.folder' "
            f"and name = '{name.replace(chr(39), chr(92)+chr(39))}' "
            f"and trashed = false"
        )
        if parent_id:
            q += f" and '{parent_id}' in parents"
        resp = self._service.files().list(
            q=q, fields="files(id, name)", pageSize=1,
        ).execute()
        files = resp.get("files", [])
        return files[0]["id"] if files else None

    def create_folder(self, *, name: str, parent_id) -> str:
        body = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            body["parents"] = [parent_id]
        resp = self._service.files().create(
            body=body, fields="id",
        ).execute()
        return resp["id"]

    def upload_file(
        self,
        *,
        name: str,
        parent_id: str,
        content: bytes,
        mime_type: str,
    ) -> dict:
        body = {"name": name, "parents": [parent_id]}
        media = MediaIoBaseUpload(io.BytesIO(content),
                                  mimetype=mime_type, resumable=False)
        resp = self._service.files().create(
            body=body, media_body=media,
            fields="id, webViewLink",
        ).execute()
        return {"file_id": resp["id"], "url": resp.get("webViewLink", "")}

    # --- Read / list operations (added Phase 8) ---
    def list_children(self, *, parent_id: str, limit: int = 100) -> list:
        """List files + folders directly under parent_id (one level)."""
        q = f"'{parent_id}' in parents and trashed = false"
        resp = self._service.files().list(
            q=q, pageSize=min(limit, 1000),
            fields="files(id, name, mimeType, size, modifiedTime, webViewLink)",
            orderBy="name",
        ).execute()
        return resp.get("files", [])

    def get_file_metadata(self, *, file_id: str) -> dict:
        """Return name + mimeType + webViewLink + size + parents."""
        return self._service.files().get(
            fileId=file_id,
            fields="id, name, mimeType, size, modifiedTime, webViewLink, parents",
        ).execute()

    def download_file_bytes(self, *, file_id: str) -> bytes:
        """Stream the file's binary content."""
        from googleapiclient.http import MediaIoBaseDownload
        request = self._service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()

    def search_files(self, *, name_contains: str = "",
                     parent_id: str = "", limit: int = 25) -> list:
        """Find files by partial name match. Scoped under parent_id when given."""
        clauses = ["trashed = false"]
        if name_contains:
            safe = name_contains.replace("'", "\\'")
            clauses.append(f"name contains '{safe}'")
        if parent_id:
            clauses.append(f"'{parent_id}' in parents")
        q = " and ".join(clauses)
        resp = self._service.files().list(
            q=q, pageSize=min(limit, 1000),
            fields="files(id, name, mimeType, size, modifiedTime, webViewLink)",
            orderBy="modifiedTime desc",
        ).execute()
        return resp.get("files", [])
