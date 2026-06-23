"""Gmail client for Goldman's agent capabilities.

Wraps the existing `gmail.auth.GmailAuth` token loader to expose
search / read / draft operations Goldman can call as tools.

Scope: must include `https://www.googleapis.com/auth/gmail.modify` for
draft creation. The existing Wise-watcher token already requests modify,
so we reuse it via GMAIL_CREDENTIALS_B64 / GMAIL_TOKEN_B64.
"""

from __future__ import annotations

import base64
import os
from email.mime.text import MIMEText
from typing import Optional


class GoldmanGmailConfigError(RuntimeError):
    pass


def _build_service():
    creds_b64 = os.getenv("GMAIL_CREDENTIALS_B64", "")
    token_b64 = os.getenv("GMAIL_TOKEN_B64", "")
    if not creds_b64 or not token_b64:
        raise GoldmanGmailConfigError(
            "GMAIL_CREDENTIALS_B64 / GMAIL_TOKEN_B64 not set."
        )
    from gmail.auth import GmailAuth
    auth = GmailAuth(credentials_b64=creds_b64, token_b64=token_b64)
    return auth.build_service()


def build_personal_service():
    """Build a Gmail service for Liran's PERSONAL inbox (liranhamburg@gmail.com).

    SaaS subscription receipts (Notion, Miro, Lovable, Meshy, Sellerboard…)
    arrive here, not in the AMZ-Expert work inbox. Reuses the same OAuth client
    (GMAIL_CREDENTIALS_B64) with a separate token.
    """
    creds_b64 = os.getenv("GMAIL_CREDENTIALS_B64", "")
    token_b64 = os.getenv("GOLDMAN_PERSONAL_GMAIL_TOKEN_B64", "")
    if not creds_b64 or not token_b64:
        raise GoldmanGmailConfigError(
            "GMAIL_CREDENTIALS_B64 / GOLDMAN_PERSONAL_GMAIL_TOKEN_B64 not set."
        )
    from gmail.auth import GmailAuth
    auth = GmailAuth(credentials_b64=creds_b64, token_b64=token_b64)
    return auth.build_service()


class GoldmanGmailClient:
    """Thin Gmail surface: search, read, draft. Send is intentionally absent."""

    def __init__(self):
        self._service = _build_service()
        self._user_id = "me"

    def search(self, *, query: str, limit: int = 10) -> list:
        """Run a Gmail search ('from:foo subject:bar after:2026/01/01').

        Returns a list of dicts: {id, threadId, subject, from, date, snippet}.
        """
        if not query.strip():
            return []
        resp = self._service.users().messages().list(
            userId=self._user_id, q=query, maxResults=min(limit, 50),
        ).execute()
        messages = resp.get("messages", []) or []
        results = []
        for m in messages:
            full = self._service.users().messages().get(
                userId=self._user_id, id=m["id"],
                format="metadata",
                metadataHeaders=["Subject", "From", "Date", "To"],
            ).execute()
            results.append(_format_message_summary(full))
        return results

    def get_thread(self, *, thread_id: str) -> dict:
        """Return all messages in a thread with their plaintext bodies."""
        thread = self._service.users().threads().get(
            userId=self._user_id, id=thread_id, format="full",
        ).execute()
        out = {"thread_id": thread_id, "messages": []}
        for msg in thread.get("messages", []):
            summary = _format_message_summary(msg)
            summary["body_text"] = _extract_plaintext(msg.get("payload", {}))
            out["messages"].append(summary)
        return out

    def create_draft_reply(self, *, thread_id: str, to: str,
                           subject: str, body: str,
                           in_reply_to_message_id: Optional[str] = None) -> dict:
        """Create a draft. User sends it from Gmail (we never auto-send)."""
        mime = MIMEText(body)
        mime["To"] = to
        mime["Subject"] = subject
        if in_reply_to_message_id:
            mime["In-Reply-To"] = in_reply_to_message_id
            mime["References"] = in_reply_to_message_id
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")
        message_body = {"raw": raw}
        if thread_id:
            message_body["threadId"] = thread_id
        draft = self._service.users().drafts().create(
            userId=self._user_id,
            body={"message": message_body},
        ).execute()
        return {
            "draft_id": draft["id"],
            "message_id": draft.get("message", {}).get("id"),
            "thread_id": draft.get("message", {}).get("threadId"),
        }


def _format_message_summary(msg: dict) -> dict:
    headers = {h["name"].lower(): h["value"]
               for h in msg.get("payload", {}).get("headers", [])}
    return {
        "message_id": msg.get("id"),
        "thread_id": msg.get("threadId"),
        "subject": headers.get("subject", ""),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "date": headers.get("date", ""),
        "snippet": msg.get("snippet", ""),
    }


def _extract_plaintext(payload: dict) -> str:
    """Walk MIME parts and return the first text/plain content found."""
    mime = (payload or {}).get("mimeType", "")
    if mime == "text/plain":
        data = (payload.get("body", {}) or {}).get("data", "")
        if data:
            return _decode_base64url(data)
    for part in (payload.get("parts", []) or []):
        text = _extract_plaintext(part)
        if text:
            return text
    return ""


def _decode_base64url(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    except Exception:
        return ""
