from __future__ import annotations

from typing import Mapping, Any


COPY_ENGLISH_TITLE = "english_title"
COPY_ROMAJI_TITLE = "romaji_title"
COPY_ANILIST_ID = "anilist_id"
COPY_SELECTED_ROW = "selected_row"


def copy_value(row: Mapping[str, Any], action: str) -> str:
    if action == COPY_ENGLISH_TITLE:
        return str(row.get("english_title") or "")
    if action == COPY_ROMAJI_TITLE:
        return str(row.get("romaji_title") or "")
    if action == COPY_ANILIST_ID:
        value = row.get("anilist_id")
        return "" if value is None else str(value)
    if action == COPY_SELECTED_ROW:
        return "\t".join(
            str(row.get(key) or "")
            for key in (
                "english_title",
                "romaji_title",
                "anilist_id",
                "season",
                "year",
                "format",
                "airing_status",
                "tracker_status",
                "server_status",
                "detected_server_path",
            )
        )
    raise ValueError(f"Unknown copy action: {action}")


def default_copy_value(row: Mapping[str, Any]) -> str:
    return str(row.get("english_title") or row.get("romaji_title") or "")


def row_to_select(identified_row: str) -> str | None:
    return identified_row or None
