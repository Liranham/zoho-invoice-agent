"""Tests for the Drive folder helper."""

from __future__ import annotations

from unittest.mock import MagicMock

from goldman.drive.folders import ensure_path


def test_ensure_path_returns_existing_when_found():
    drive = MagicMock()
    drive.find_folder.side_effect = ["root_id", "amzg_id", "2026_id", "june_id"]

    folder_id = ensure_path(
        drive,
        ["Goldman Bills", "AMZ Expert Global Limited", "2026", "June"],
    )

    assert folder_id == "june_id"
    assert drive.find_folder.call_count == 4
    assert drive.create_folder.call_count == 0


def test_ensure_path_creates_missing_levels():
    drive = MagicMock()
    drive.find_folder.side_effect = [
        "root_id",      # Goldman Bills found
        "amzg_id",      # AMZ Expert Global Limited found
        None,           # 2026 missing
        None,           # June missing
    ]
    drive.create_folder.side_effect = ["2026_id", "june_id"]

    folder_id = ensure_path(
        drive,
        ["Goldman Bills", "AMZ Expert Global Limited", "2026", "June"],
    )

    assert folder_id == "june_id"
    assert drive.create_folder.call_count == 2
