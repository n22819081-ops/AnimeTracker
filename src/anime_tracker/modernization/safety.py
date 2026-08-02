from __future__ import annotations

from pathlib import Path


DEFAULT_PROTECTED_ROOTS = (
    Path(r"I:\Jellyfin_Media\TV-SHOWs"),
    Path(r"I:\Jellyfin_Media\Movies"),
    Path(r"I:\Jellyfin_Media\Anime"),
)


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
