from __future__ import annotations

from datetime import datetime
from typing import Iterable

from .enums import RejectionScope, ReviewStatus, TrackingContentKind
from .models import DomainWarning, MediaServerMapping, RejectedMatchDecision, ReviewCase


def active_mappings(mappings: Iterable[MediaServerMapping]) -> tuple[MediaServerMapping, ...]:
    return tuple(item for item in mappings if item.active and item.superseded_at is None)


def mapping_fingerprint(mappings: Iterable[MediaServerMapping]) -> str:
    values = (
        f"{item.anilist_id}|{item.stable_item_id}|{item.path.casefold()}|{item.season_number}|{item.content_kind.value}"
        for item in active_mappings(mappings)
    )
    return "\n".join(sorted(values))


def validate_mappings(tracked_id: str, mappings: Iterable[MediaServerMapping]) -> tuple[ReviewCase, ...]:
    active = active_mappings(mappings)
    cases: list[ReviewCase] = []
    season_targets: dict[tuple[int, str, str], set[int | None]] = {}
    targets_by_anilist: dict[int, set[tuple[str, str]]] = {}
    for item in active:
        target = (item.stable_item_id, item.path.casefold())
        targets_by_anilist.setdefault(item.anilist_id, set()).add(target)
        scoped_target = (item.anilist_id, *target)
        season_targets.setdefault(scoped_target, set()).add(item.season_number)
        if item.library_kind.value == "TV" and item.content_kind == TrackingContentKind.MOVIE and item.source.value != "USER":
            cases.append(ReviewCase(
                f"movie-tv:{item.mapping_id}", tracked_id, ReviewStatus.IDENTITY_CONFLICT,
                "MOVIE_MAPPED_TO_TV", "A movie is mapped to a TV item without manual approval.",
            ))
    for anilist_id, distinct_targets in targets_by_anilist.items():
        items = tuple(item for item in active if item.anilist_id == anilist_id)
        if len(distinct_targets) > 1 and not all(item.allows_multiple_targets for item in items):
            cases.append(ReviewCase(
                f"multiple-targets:{anilist_id}", tracked_id, ReviewStatus.CONFLICTING_MATCHES,
                "MULTIPLE_ACTIVE_TARGETS", "The entry has multiple active server targets without explicit multi-target approval.",
            ))
    for target, seasons in season_targets.items():
        numbered = {number for number in seasons if number is not None}
        if len(numbered) > 1:
            cases.append(ReviewCase(
                f"season-conflict:{target}", tracked_id, ReviewStatus.SEASON_MAPPING_REQUIRED,
                "CONFLICTING_SEASON_SCOPES", "One entry maps to conflicting seasons in the same server item.",
            ))
    return tuple(sorted(cases, key=lambda case: case.case_id))


def active_rejections(rejections: Iterable[RejectedMatchDecision], at: datetime | None = None) -> tuple[RejectedMatchDecision, ...]:
    return tuple(item for item in rejections if item.active and (item.expires_at is None or at is None or item.expires_at > at))


def is_candidate_rejected(
    rejections: Iterable[RejectedMatchDecision],
    *,
    candidate_id: str = "",
    stable_item_id: str = "",
    path: str = "",
    at: datetime | None = None,
) -> bool:
    for item in active_rejections(rejections, at):
        if item.scope == RejectionScope.SUPPRESS_AUTOMATIC_MATCHING:
            return True
        if item.scope == RejectionScope.CANDIDATE and item.target == candidate_id:
            return True
        if item.scope == RejectionScope.LIBRARY_ITEM and item.target == stable_item_id:
            return True
        if item.scope == RejectionScope.EXACT_PATH and item.target.casefold() == path.casefold():
            return True
    return False


def mapping_warnings(mappings: Iterable[MediaServerMapping]) -> tuple[DomainWarning, ...]:
    return tuple(
        DomainWarning("UNCONFIRMED_MAPPING", f"Mapping {item.mapping_id} is proposed but not confirmed.")
        for item in active_mappings(mappings) if not item.is_confirmed
    )
