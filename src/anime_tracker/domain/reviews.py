from __future__ import annotations

from typing import Iterable

from .enums import MediaKind, ReviewStatus
from .models import MatchCandidateEvidence, MediaServerMapping, ReviewCase
from .mappings import validate_mappings


def generate_review_cases(
    *,
    tracked_id: str,
    candidates: Iterable[MatchCandidateEvidence] = (),
    mappings: Iterable[MediaServerMapping] = (),
    confirmed_path_missing: bool = False,
    identity_conflict: bool = False,
    media_kind: MediaKind = MediaKind.UNKNOWN,
    special_mapping_resolved: bool = True,
    legacy_orphan: bool = False,
    score_tolerance: int = 0,
) -> tuple[ReviewCase, ...]:
    candidates = tuple(candidates)
    cases = list(validate_mappings(tracked_id, mappings))
    if len(candidates) >= 2:
        ordered = sorted(candidates, key=lambda item: (-item.score, item.candidate_id))
        if abs(ordered[0].score - ordered[1].score) <= score_tolerance:
            cases.append(ReviewCase(
                "ambiguous-candidates", tracked_id, ReviewStatus.AMBIGUOUS_MATCH,
                "EQUALLY_STRONG_CANDIDATES", "Two or more server candidates are equally strong.",
            ))
    if confirmed_path_missing:
        cases.append(ReviewCase(
            "missing-confirmed-path", tracked_id, ReviewStatus.MISSING_CONFIRMED_PATH,
            "CONFIRMED_PATH_MISSING", "A previously confirmed server path is missing.",
        ))
    if identity_conflict:
        cases.append(ReviewCase(
            "identity-conflict", tracked_id, ReviewStatus.IDENTITY_CONFLICT,
            "PROVIDER_IDENTITY_CONFLICT", "Stored mapping identity conflicts with the provider identity.",
        ))
    if media_kind in {MediaKind.SPECIAL, MediaKind.OVA, MediaKind.ONA} and not special_mapping_resolved:
        cases.append(ReviewCase(
            "special-mapping", tracked_id, ReviewStatus.SPECIAL_MAPPING_REQUIRED,
            "SPECIAL_PARENT_UNRESOLVED", "The special or OVA parent/server target is unresolved.",
        ))
    if legacy_orphan:
        cases.append(ReviewCase(
            "legacy-orphan", tracked_id, ReviewStatus.LEGACY_DATA_REVIEW,
            "LEGACY_ORPHAN", "A preserved legacy record has no verified active owner.",
        ))
    return tuple(sorted(cases, key=lambda case: case.case_id))
