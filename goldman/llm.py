"""Thin Anthropic SDK wrapper for Goldman.

Phase 1 only needs structured extraction via tool use; later phases will
add conversation routing, streaming, and prompt caching. The wrapper keeps
that future surface area minimal.
"""

from __future__ import annotations

import os
from typing import Optional

import anthropic


DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 4096


class LLMConfigError(RuntimeError):
    """Raised when the Anthropic API key is missing or unusable."""


class GoldmanLLM:
    def __init__(self, *, model: str = DEFAULT_MODEL, max_tokens: int = DEFAULT_MAX_TOKENS):
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise LLMConfigError(
                "ANTHROPIC_API_KEY not set. Goldman needs it for the onboarding "
                "extractor (same key as HQ Hub uses for Atlas)."
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens

    def extract_with_tool(
        self,
        *,
        system: str,
        user_text: str,
        tool_name: str,
        tool_schema: dict,
    ) -> dict:
        """Send the prompt; force the model to call the given tool; return its input."""
        response = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_text}],
            tools=[{
                "name": tool_name,
                "description": "Submit the structured extraction.",
                "input_schema": tool_schema,
            }],
            tool_choice={"type": "tool", "name": tool_name},
        )

        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
                return dict(block.input)

        raise RuntimeError(
            f"Claude did not call the tool {tool_name!r}; "
            f"stop_reason={response.stop_reason!r}"
        )


SUMMARY_MODEL = "claude-haiku-4-5-20251001"


class DocumentSummariser:
    """One-shot two-sentence summary via Claude Haiku."""

    def __init__(self, *, model: str = SUMMARY_MODEL):
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise LLMConfigError(
                "ANTHROPIC_API_KEY not set. DocumentSummariser needs it."
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def summarise(self, text: str, *, max_chars: int = 12000) -> str:
        clipped = text if len(text) <= max_chars else text[:max_chars]
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": (
                    "Summarise this document in 2-3 sentences. Focus on what "
                    "it is and key points. Output the summary only, no preamble.\n\n"
                    + clipped
                ),
            }],
        )
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                return block.text.strip()
        return ""


# Document/image extraction (Phase 3)
def _document_extract_with_tool(client, model, max_tokens, document_path,
                                 system, tool_name, tool_schema):
    """Internal helper — exists at module level for testability."""
    import base64
    import mimetypes
    from pathlib import Path
    path = Path(document_path)
    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "application/octet-stream"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")

    if mime == "application/pdf":
        doc_block = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf",
                        "data": b64},
        }
    elif mime.startswith("image/"):
        doc_block = {
            "type": "image",
            "source": {"type": "base64", "media_type": mime, "data": b64},
        }
    else:
        # Spreadsheets (.xlsx), Word docs (.docx), CSV, plain text, etc.
        # An .xlsx is a binary zip — read_text() on it yields gibberish, which
        # is why Goldman used to say "I only see metadata" and couldn't tell
        # which company a Wise statement belonged to. Route through the real
        # extractors so Claude sees the actual cell/paragraph contents.
        try:
            from goldman.documents import _read_text
            extracted = _read_text(path, mime)
        except Exception:
            extracted = ""
        doc_block = {"type": "text",
                     "text": extracted or path.read_text(errors="replace")}

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": [doc_block]}],
        tools=[{
            "name": tool_name,
            "description": "Submit the structured extraction.",
            "input_schema": tool_schema,
        }],
        tool_choice={"type": "tool", "name": tool_name},
    )
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
            return dict(block.input)
    raise RuntimeError(
        f"Claude did not call the tool {tool_name!r}; "
        f"stop_reason={response.stop_reason!r}"
    )


# Bind it as a method on GoldmanLLM
def _extract_from_document(self, *, document_path, system, tool_name, tool_schema):
    """Send a file as a document/image content block + a tool. Return tool input."""
    return _document_extract_with_tool(
        self._client, self.model, self.max_tokens,
        document_path, system, tool_name, tool_schema,
    )


GoldmanLLM.extract_from_document = _extract_from_document


# OCR-via-vision fallback for image-only / scanned PDFs.
# pypdf returns empty text on these; Claude vision reads the page images.
def vision_extract_text(*, file_path, model: str = "claude-haiku-4-5-20251001",
                        max_tokens: int = 4096) -> str:
    """Send the file (PDF or image) to Claude vision and ask for verbatim text.

    Used as fallback when pypdf returns ~0 characters (scanned / image-only).
    Returns raw extracted text; empty string if nothing readable.
    """
    import base64
    import mimetypes
    from pathlib import Path

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise LLMConfigError("ANTHROPIC_API_KEY not set; vision OCR unavailable.")

    path = Path(file_path)
    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "application/octet-stream"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")

    if mime == "application/pdf":
        media_block = {"type": "document",
                       "source": {"type": "base64",
                                  "media_type": "application/pdf",
                                  "data": b64}}
    elif mime.startswith("image/"):
        media_block = {"type": "image",
                       "source": {"type": "base64",
                                  "media_type": mime,
                                  "data": b64}}
    else:
        return ""

    client = anthropic.Anthropic(api_key=api_key)
    prompt = (
        "Extract every piece of legible text from this document, verbatim. "
        "Preserve structure (line breaks, tables as pipe-separated rows, "
        "field labels colon-separated). Do not paraphrase, summarise, or "
        "add commentary — only the text that appears on the page. If a "
        "field is illegible, write [illegible] in its place."
    )
    resp = client.messages.create(
        model=model, max_tokens=max_tokens,
        messages=[{"role": "user",
                   "content": [media_block, {"type": "text", "text": prompt}]}],
    )
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            return block.text.strip()
    return ""
