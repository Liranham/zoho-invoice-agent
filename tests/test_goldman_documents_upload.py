"""Tests for upload_document flow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from pathlib import Path
from uuid import uuid4

import pytest

from goldman.documents import upload_document


def test_upload_uploads_writes_doc_and_chunks(monkeypatch, tmp_path):
    f = tmp_path / "letter.txt"
    f.write_text("This is a short advisor letter.")

    storage = MagicMock()
    storage.upload = MagicMock()
    doc_repo = MagicMock()
    new_doc_id = uuid4()
    doc_repo.insert.return_value = new_doc_id
    chunk_repo = MagicMock()
    chunk_repo.insert.return_value = uuid4()
    summariser = MagicMock()
    summariser.summarise.return_value = "A short letter."

    eid = uuid4()
    result = upload_document(
        file_path=f,
        entity_id=eid,
        entity_slug="amzg",
        storage=storage,
        doc_repo=doc_repo,
        chunk_repo=chunk_repo,
        summariser=summariser,
        bucket="goldman-documents",
        source="uploaded",
    )

    storage.upload.assert_called_once()
    bucket = storage.upload.call_args.kwargs["bucket"]
    assert bucket == "goldman-documents"

    doc_repo.insert.assert_called_once()
    insert_kwargs = doc_repo.insert.call_args.kwargs
    assert insert_kwargs["entity_id"] == eid
    assert insert_kwargs["filename"] == "letter.txt"

    doc_repo.set_summary.assert_called_once_with(new_doc_id, "A short letter.")

    assert chunk_repo.insert.call_count >= 1
    assert result.document_id == new_doc_id
    assert result.chunk_count >= 1


def test_upload_extracts_text_from_pdf(monkeypatch, tmp_path):
    f = tmp_path / "report.pdf"
    f.write_bytes(b"%PDF-1.4\n")

    with patch("goldman.documents.extract_text_from_pdf") as mock_extract:
        mock_extract.return_value = (
            "Extracted PDF text. " * 5  # >50 chars so OCR fallback is skipped
        )

        storage = MagicMock()
        doc_repo = MagicMock()
        doc_repo.insert.return_value = uuid4()
        chunk_repo = MagicMock()
        chunk_repo.insert.return_value = uuid4()
        summariser = MagicMock()
        summariser.summarise.return_value = "Summary"

        upload_document(
            file_path=f,
            entity_id=uuid4(),
            entity_slug="amzg",
            storage=storage,
            doc_repo=doc_repo,
            chunk_repo=chunk_repo,
            summariser=summariser,
            bucket="goldman-documents",
        )

        mock_extract.assert_called_once()
        chunk_text_arg = chunk_repo.insert.call_args.kwargs["text"]
        assert "Extracted PDF text." in chunk_text_arg


def test_upload_strips_nul_bytes_from_extracted_pdf_text(tmp_path):
    """Postgres text columns reject NUL (0x00).

    pypdf decodes some fonts into strings carrying embedded NULs. Before this
    guard the chunk INSERT raised psycopg.DataError and killed the whole
    Telegram reply — the invoice was never filed and Liran just saw an error.
    """
    f = tmp_path / "invoice.pdf"
    f.write_bytes(b"%PDF-1.4\n")

    with patch("goldman.documents.extract_text_from_pdf") as mock_extract:
        mock_extract.return_value = "Invoice BBDEC7B1-0053\x00 total USD 240.00 " * 3

        storage = MagicMock()
        doc_repo = MagicMock()
        doc_repo.insert.return_value = uuid4()
        chunk_repo = MagicMock()
        chunk_repo.insert.return_value = uuid4()
        summariser = MagicMock()
        summariser.summarise.return_value = "An invoice."

        upload_document(
            file_path=f,
            entity_id=uuid4(),
            entity_slug="amzg",
            storage=storage,
            doc_repo=doc_repo,
            chunk_repo=chunk_repo,
            summariser=summariser,
            bucket="goldman-documents",
        )

        assert chunk_repo.insert.call_count >= 1
        for call in chunk_repo.insert.call_args_list:
            assert "\x00" not in call.kwargs["text"]
        # The real content survives — we strip the NUL, not the text around it.
        assert "BBDEC7B1-0053" in chunk_repo.insert.call_args_list[0].kwargs["text"]
        # The summariser must not be handed NULs either.
        assert "\x00" not in summariser.summarise.call_args.args[0]


def test_upload_pack_uses_override_path_and_passes_pack_metadata(tmp_path):
    f = tmp_path / "us_llc_tax_v1.md"
    f.write_text("# US LLC Tax v1\n\n## Entity classification\n\nLorem ipsum.")

    storage = MagicMock()
    doc_repo = MagicMock()
    new_doc_id = uuid4()
    doc_repo.insert.return_value = new_doc_id
    chunk_repo = MagicMock()
    chunk_repo.insert.return_value = uuid4()
    summariser = MagicMock()
    summariser.summarise.return_value = "Reference pack on US LLC tax."

    result = upload_document(
        file_path=f,
        entity_id=None,
        entity_slug=None,
        storage=storage,
        doc_repo=doc_repo,
        chunk_repo=chunk_repo,
        summariser=summariser,
        bucket="goldman-documents",
        source="knowledge_pack",
        pack_topic="us_llc_tax",
        pack_version="v1-2026-06",
        storage_path_override="packs/us_llc_tax/v1-2026-06/us_llc_tax_v1.md",
    )

    storage.upload.assert_called_once()
    upload_kwargs = storage.upload.call_args.kwargs
    assert upload_kwargs["path"] == "packs/us_llc_tax/v1-2026-06/us_llc_tax_v1.md"

    doc_repo.insert.assert_called_once()
    insert_kwargs = doc_repo.insert.call_args.kwargs
    assert insert_kwargs["entity_id"] is None
    assert insert_kwargs["source"] == "knowledge_pack"
    assert insert_kwargs["pack_topic"] == "us_llc_tax"
    assert insert_kwargs["pack_version"] == "v1-2026-06"
    assert insert_kwargs["original_storage_path"] == "packs/us_llc_tax/v1-2026-06/us_llc_tax_v1.md"

    assert result.document_id == new_doc_id
    assert result.storage_path == "packs/us_llc_tax/v1-2026-06/us_llc_tax_v1.md"


# --- Regression: the 2026-06-23 silent-bot bug -----------------------------
# A Telegram photo (a screenshot of the HK CPA's WhatsApp message) reached
# upload_document named "document.pdf" because Telegram PhotoSize objects have
# no filename. The old code trusted the .pdf extension, fed JPEG bytes to
# pypdf, and crashed with PdfStreamError — leaving Goldman silent. The reader
# must now sniff the real bytes and route the image to vision OCR instead.

# JPEG magic bytes (SOI + APP0/JFIF) — enough for _sniff_mime to identify it.
_FAKE_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 64


def test_jpeg_misnamed_as_pdf_uses_vision_not_pypdf(tmp_path):
    """A screenshot named 'document.pdf' must NOT crash; it should OCR."""
    f = tmp_path / "document.pdf"   # wrong extension on purpose
    f.write_bytes(_FAKE_JPEG)

    with patch("goldman.documents.extract_text_from_pdf") as mock_pdf, \
         patch("goldman.llm.vision_extract_text") as mock_vision:
        mock_vision.return_value = "Hey Liran, this is the CPA's message ..."

        storage = MagicMock()
        doc_repo = MagicMock()
        doc_repo.insert.return_value = uuid4()
        chunk_repo = MagicMock()
        chunk_repo.insert.return_value = uuid4()
        summariser = MagicMock()
        summariser.summarise.return_value = "CPA message."

        result = upload_document(
            file_path=f,
            entity_id=uuid4(),
            entity_slug="amzg",
            storage=storage,
            doc_repo=doc_repo,
            chunk_repo=chunk_repo,
            summariser=summariser,
            bucket="goldman-documents",
        )

    # pypdf must never be invoked on JPEG bytes; vision OCR handles it.
    mock_pdf.assert_not_called()
    mock_vision.assert_called_once()
    chunk_text_arg = chunk_repo.insert.call_args.kwargs["text"]
    assert "CPA's message" in chunk_text_arg
    assert result.chunk_count >= 1


def test_corrupt_pdf_falls_back_to_vision_instead_of_crashing(tmp_path):
    """A genuinely-broken PDF must degrade to OCR, never raise."""
    f = tmp_path / "broken.pdf"
    f.write_bytes(b"%PDF-1.4\nthen truncated garbage")  # real PDF header, broken body

    def _boom(_path):
        from pypdf.errors import PdfStreamError
        raise PdfStreamError("Stream has ended unexpectedly")

    with patch("goldman.documents.extract_text_from_pdf", side_effect=_boom), \
         patch("goldman.llm.vision_extract_text") as mock_vision:
        mock_vision.return_value = "Recovered via OCR " * 5

        storage = MagicMock()
        doc_repo = MagicMock()
        doc_repo.insert.return_value = uuid4()
        chunk_repo = MagicMock()
        chunk_repo.insert.return_value = uuid4()
        summariser = MagicMock()
        summariser.summarise.return_value = "Recovered."

        result = upload_document(
            file_path=f,
            entity_id=uuid4(),
            entity_slug="amzg",
            storage=storage,
            doc_repo=doc_repo,
            chunk_repo=chunk_repo,
            summariser=summariser,
            bucket="goldman-documents",
        )

    mock_vision.assert_called_once()
    assert result.chunk_count >= 1
