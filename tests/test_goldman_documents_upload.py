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
        mock_extract.return_value = "Extracted PDF text."

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
