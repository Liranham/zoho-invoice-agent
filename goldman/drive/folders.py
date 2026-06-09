"""Find-or-create a nested folder path in Google Drive.

Each level lookup uses parent_id + name match.
"""

from __future__ import annotations

from typing import Optional


def ensure_path(drive_client, path_segments: list,
                *, root_id: Optional[str] = None) -> str:
    """Walk a path, creating any segments that don't exist. Return leaf folder id.

    When `root_id` is provided, the first segment is created under that
    folder (e.g. Liran's pre-existing shared backup folder) instead of
    Drive root.
    """
    parent_id: Optional[str] = root_id
    for name in path_segments:
        existing = drive_client.find_folder(name=name, parent_id=parent_id)
        if existing is None:
            existing = drive_client.create_folder(name=name, parent_id=parent_id)
        parent_id = existing
    return parent_id
