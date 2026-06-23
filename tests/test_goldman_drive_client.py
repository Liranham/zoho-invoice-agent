"""Tests for GoogleDriveClient."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from goldman.drive.client import GoogleDriveClient, DriveConfigError


def test_raises_when_no_credentials(monkeypatch):
    monkeypatch.delenv("GOLDMAN_DRIVE_CREDENTIALS_B64", raising=False)
    monkeypatch.delenv("GOLDMAN_DRIVE_TOKEN_B64", raising=False)

    with pytest.raises(DriveConfigError):
        GoogleDriveClient()


def test_find_folder_queries_drive_api():
    with patch("goldman.drive.client.build") as mock_build:
        svc = MagicMock()
        mock_build.return_value = svc
        svc.files.return_value.list.return_value.execute.return_value = {
            "files": [{"id": "amzg_id", "name": "AMZ Expert Global Limited"}],
        }

        c = GoogleDriveClient.__new__(GoogleDriveClient)
        c._service = svc

        fid = c.find_folder(name="AMZ Expert Global Limited", parent_id="root_id")

        assert fid == "amzg_id"
        list_kwargs = svc.files.return_value.list.call_args.kwargs
        assert "AMZ Expert Global Limited" in list_kwargs["q"]
        assert "root_id" in list_kwargs["q"]


def test_create_folder_calls_drive_api():
    with patch("goldman.drive.client.build") as mock_build:
        svc = MagicMock()
        mock_build.return_value = svc
        svc.files.return_value.create.return_value.execute.return_value = {
            "id": "new_folder_id",
        }

        c = GoogleDriveClient.__new__(GoogleDriveClient)
        c._service = svc

        fid = c.create_folder(name="June", parent_id="2026_id")

        assert fid == "new_folder_id"
        body = svc.files.return_value.create.call_args.kwargs["body"]
        assert body["name"] == "June"
        assert body["mimeType"] == "application/vnd.google-apps.folder"


def test_upload_file_calls_drive_api():
    with patch("goldman.drive.client.build") as mock_build, \
         patch("goldman.drive.client.MediaIoBaseUpload") as mock_media:
        svc = MagicMock()
        mock_build.return_value = svc
        svc.files.return_value.create.return_value.execute.return_value = {
            "id": "file_xyz",
            "webViewLink": "https://drive.google.com/file/d/file_xyz/view",
        }

        c = GoogleDriveClient.__new__(GoogleDriveClient)
        c._service = svc

        result = c.upload_file(
            name="bill.pdf",
            parent_id="june_id",
            content=b"%PDF...",
            mime_type="application/pdf",
        )

        assert result["file_id"] == "file_xyz"
        assert "drive.google.com" in result["url"]


def test_list_sheet_tabs_returns_titles():
    c = GoogleDriveClient.__new__(GoogleDriveClient)
    c._sheets = MagicMock()
    c._sheets.spreadsheets.return_value.get.return_value.execute.return_value = {
        "sheets": [
            {"properties": {"title": "May26"}},
            {"properties": {"title": "June26"}},
        ]
    }
    assert c.list_sheet_tabs(file_id="s1") == ["May26", "June26"]


def test_read_sheet_values_uses_tab_range_and_caps_rows():
    c = GoogleDriveClient.__new__(GoogleDriveClient)
    c._sheets = MagicMock()
    values_get = c._sheets.spreadsheets.return_value.values.return_value.get
    values_get.return_value.execute.return_value = {
        "values": [["a", "1"], ["b", "2"], ["c", "3"]]
    }
    rows = c.read_sheet_values(file_id="s1", tab="June26", max_rows=2)
    assert rows == [["a", "1"], ["b", "2"]]
    assert values_get.call_args.kwargs["range"] == "'June26'"


def test_export_text_decodes_bytes():
    with patch("goldman.drive.client.build"):
        c = GoogleDriveClient.__new__(GoogleDriveClient)
        c._service = MagicMock()
        c._service.files.return_value.export.return_value.execute.return_value = (
            b"Hello offsets"
        )
        out = c.export_text(file_id="doc1")
        assert out == "Hello offsets"
