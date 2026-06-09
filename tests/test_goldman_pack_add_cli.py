"""Tests for the `pack add` CLI command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from click.testing import CliRunner


def test_pack_add_calls_upload_document_with_pack_fields(tmp_path):
    f = tmp_path / "us_llc_tax_v1.md"
    f.write_text("# US LLC Tax v1\n\nLorem ipsum.")

    fake_result = MagicMock(
        document_id=uuid4(), chunk_count=5,
        storage_path="packs/us_llc_tax/v1-2026-06/us_llc_tax_v1.md",
    )

    with patch("cli.SupabaseStorage", autospec=False) as _MockStorage, \
         patch("cli.DocumentSummariser", autospec=False) as _MockSumm, \
         patch("cli.upload_document", return_value=fake_result) as mock_upload, \
         patch("cli.app_conn") as _MockConn:
        _MockStorage.return_value = MagicMock()
        _MockSumm.return_value = MagicMock()
        _MockConn.return_value.__enter__.return_value = MagicMock()

        from cli import cli as cli_app
        runner = CliRunner()
        result = runner.invoke(
            cli_app,
            ["pack", "add", str(f),
             "--topic", "us_llc_tax",
             "--version", "v1-2026-06"],
        )

        assert result.exit_code == 0, result.output
        mock_upload.assert_called_once()
        kwargs = mock_upload.call_args.kwargs
        assert kwargs["source"] == "knowledge_pack"
        assert kwargs["pack_topic"] == "us_llc_tax"
        assert kwargs["pack_version"] == "v1-2026-06"
        assert kwargs["storage_path_override"] == "packs/us_llc_tax/v1-2026-06/us_llc_tax_v1.md"
        assert kwargs["entity_id"] is None
        assert kwargs["entity_slug"] is None
        assert kwargs["bucket"] == "goldman-documents"
