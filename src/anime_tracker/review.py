from __future__ import annotations

from .constants import REVIEW_NO_MATCH, REVIEW_POSSIBLE_MATCHES


def build_review_state(row, candidates) -> dict[str, object]:
    reason = _row_value(row, "review_reason", "")
    if not reason:
        reason = REVIEW_POSSIBLE_MATCHES if candidates else REVIEW_NO_MATCH
    return {
        "reason": reason,
        "has_candidates": bool(candidates),
        "empty_message": "No possible Jellyfin matches were found.",
        "empty_detail": "This title may not be on the server, or the folder name may be too different for automatic matching.",
        "confirm_enabled": bool(candidates),
        "reject_enabled": bool(candidates),
    }


def _row_value(row, key: str, default=None):
    try:
        if hasattr(row, "keys") and key not in row.keys():
            return default
        return row[key]
    except (KeyError, IndexError):
        return default
