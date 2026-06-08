"""Find-or-create a nested folder path in Google Drive.

Each level lookup uses parent_id + name match.
"""

from __future__ import annotations

from typing import Optional


def ensure_path(drive_client, path_segments: list) -> str:
    """Walk a path, creating any segments that don't exist. Return leaf folder id."""
    parent_id: Optional[str] = None       # 'root' is implicit for the first call
    for name in path_segments:
        existing = drive_client.find_folder(name=name, parent_id=parent_id)
        if existing is None:
            existing = drive_client.create_folder(name=name, parent_id=parent_id)
        parent_id = existing
    return parent_id
