"""Modern PySide6 GUI bootstrap and Windows TLS isolation."""

from __future__ import annotations

import os
from pathlib import Path


def _safe_windows_path(value: str) -> str:
    """Keep POSIX toolchains from supplying incompatible DLLs to Qt Network."""
    if os.name != "nt":
        return value
    safe = []
    for entry in value.split(os.pathsep):
        folded = entry.casefold()
        is_posix_toolchain = any(part in folded for part in ("\\msys", "\\cygwin", "\\mingw"))
        if is_posix_toolchain and (Path(entry) / "libssl-3-x64.dll").is_file():
            continue
        safe.append(entry)
    return os.pathsep.join(safe)


if os.name == "nt":
    os.environ["PATH"] = _safe_windows_path(os.environ.get("PATH", ""))
