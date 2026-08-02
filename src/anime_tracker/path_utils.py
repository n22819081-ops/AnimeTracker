from __future__ import annotations


def normalize_windows_path(path: str) -> str:
    value = (path or "").strip().replace("/", "\\")
    while len(value) > 3 and value.endswith("\\"):
        value = value[:-1]
    return value.casefold()
