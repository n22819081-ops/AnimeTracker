from __future__ import annotations

from .constants import (
    TRACKER_AIRING,
    TRACKER_MOVIE_DIGITAL,
    TRACKER_MOVIE_THEATRICAL,
    TRACKER_READY,
    TRACKER_ON_SERVER,
    TRACKER_UPCOMING,
)

MOVIE_FORMATS = {"MOVIE"}


def tracker_status_from_anilist(
    airing_status: str,
    anime_format: str,
    movie_availability: str = "unknown",
) -> str:
    if anime_format in MOVIE_FORMATS:
        if movie_availability == "digital":
            return TRACKER_MOVIE_DIGITAL
        return TRACKER_MOVIE_THEATRICAL
    if airing_status == "NOT_YET_RELEASED":
        return TRACKER_UPCOMING
    if airing_status in {"RELEASING", "HIATUS"}:
        return TRACKER_AIRING
    if airing_status == "FINISHED":
        return TRACKER_READY
    return TRACKER_UPCOMING


def is_meaningful_transition(old_status: str, new_status: str) -> bool:
    transitions = {
        (TRACKER_UPCOMING, TRACKER_AIRING),
        (TRACKER_AIRING, TRACKER_READY),
        (TRACKER_MOVIE_THEATRICAL, TRACKER_MOVIE_DIGITAL),
    }
    return (old_status, new_status) in transitions


def notification_key(anilist_id: int, old_status: str, new_status: str) -> str:
    return f"status:{anilist_id}:{old_status}->{new_status}"


def visible_tracker_status(current_tracker_status: str, anilist_status: str, anime_format: str, movie_availability: str = "unknown") -> str:
    if current_tracker_status == TRACKER_ON_SERVER:
        return TRACKER_ON_SERVER
    return tracker_status_from_anilist(anilist_status, anime_format, movie_availability)
