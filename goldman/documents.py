"""Document upload flow: storage upload + Claude summary + chunk + insert."""

from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from goldman.chunker import chunk_text


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(name: str) -> str:
    return _SAFE_NAME.sub("_", name)


def extract_text_from_pdf(file_path: Path) -> str:
    """Pull raw text from a PDF using pypdf."""
    from pypdf import PdfReader
    reader = PdfReader(str(file_path))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    return "\n\n".join(pages).strip()


def _read_text(file_path: Path, mime_type: str) -> str:
    if mime_type == "application/pdf":
        return extract_text_from_pdf(file_path)
    return file_path.read_text(errors="replace")


@dataclass
class UploadResult:
    document_id: UUID
    chunk_count: int
    storage_path: str


def upload_document(
    *,
    file_path: Path,
    entity_id: UUID,
    entity_slug: str,
    storage,
    doc_repo,
    chunk_repo,
    summariser,
    bucket: str,
    source: str = "uploaded",
    chunk_max_tokens: int = 512,
    chunk_overlap_tokens: int = 64,
) -> UploadResult:
    """Upload one document end-to-end.

    storage      — SupabaseStorage instance
    doc_repo     — DocumentRepository instance
    chunk_repo   — DocumentChunkRepository instance
    summariser   — anything with .summarise(text) -> str
    """
    mime_type, _ = mimetypes.guess_type(file_path.name)
    mime_type = mime_type or "application/octet-stream"

    # 1. Storage upload
    body = file_path.read_bytes()
    year = datetime.utcnow().year
    storage_path = f"{entity_slug}/{year}/{uuid4().hex[:8]}-{_safe_filename(file_path.name)}"
    storage.upload(
        bucket=bucket,
        path=storage_path,
        content=body,
        content_type=mime_type,
    )

    # 2. Insert metadata row
    doc_id = doc_repo.insert(
        entity_id=entity_id,
        filename=file_path.name,
        mime_type=mime_type,
        source=source,
        original_storage_path=storage_path,
    )

    # 3. Extract text and chunk
    text = _read_text(file_path, mime_type)
    chunks = chunk_text(
        text,
        max_tokens=chunk_max_tokens,
        overlap_tokens=chunk_overlap_tokens,
    )

    # 4. Insert chunks
    for idx, chunk in enumerate(chunks):
        chunk_repo.insert(
            document_id=doc_id,
            chunk_index=idx,
            text=chunk,
        )

    # 5. Summarise (one-shot via Claude Haiku)
    if text.strip():
        try:
            summary = summariser.summarise(text)
            doc_repo.set_summary(doc_id, summary)
        except Exception:
            # Non-fatal: chunks are searchable even without a summary.
            pass

    return UploadResult(
        document_id=doc_id,
        chunk_count=len(chunks),
        storage_path=storage_path,
    )
