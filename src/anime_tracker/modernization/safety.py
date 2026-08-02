from __future__ import annotations

import os
from pathlib import Path


_MEDIA_DRIVE=os.environ.get("ANIME_TRACKER_MEDIA_DRIVE","I:").rstrip("\\/")
_MEDIA_ROOT=Path(_MEDIA_DRIVE+"\\")/"Jellyfin_Media"
DEFAULT_PROTECTED_ROOTS=(_MEDIA_ROOT/"TV-SHOWs",_MEDIA_ROOT/"Movies",_MEDIA_ROOT/"Anime")


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def assert_safe_output_path(
    path: Path,
    *,
    protected_roots: tuple[Path, ...] = DEFAULT_PROTECTED_ROOTS,
    storage_checker_path: Path | None = None,
) -> None:
    for root in protected_roots:
        if is_within(path, root):
            raise ValueError(f"Output is forbidden inside protected media root: {root}")
    if storage_checker_path and is_within(path, storage_checker_path):
        raise ValueError("Output is forbidden inside the separate Jellyfin Storage Checker.")
