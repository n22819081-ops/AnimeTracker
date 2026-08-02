from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Iterable

from ...domain.enums import MediaKind
from ..anilist.models import AniListMedia
from .models import (
    CandidateGenerationResult,
    ConfirmationState,
    MatchConfidence,
    MatchingReviewCase,
    MatchingReviewType,
    PersistentMapping,
    ReviewCaseState,
    ReviewSeverity,
)


def generate_matching_reviews(
    *,
    profile_id: str,
    media: AniListMedia,
    generated: CandidateGenerationResult | None,
    mappings: Iterable[PersistentMapping],
    now: datetime,
    missing_path_mapping_ids: Iterable[str] = (),
    missing_season_mapping_ids: Iterable[str] = (),
) -> tuple[MatchingReviewCase, ...]:
    mappings = tuple(mapping for mapping in mappings if mapping.active)
    media_mappings = tuple(mapping for mapping in mappings if mapping.anilist_id == media.anilist_id)
    missing_paths = tuple(sorted(set(missing_path_mapping_ids)))
    missing_seasons = tuple(sorted(set(missing_season_mapping_ids)))
    cases: list[MatchingReviewCase] = []
    candidates = generated.candidates if generated else ()

    viable = tuple(item for item in candidates if item.confidence in {
        MatchConfidence.VERY_STRONG, MatchConfidence.STRONG, MatchConfidence.POSSIBLE,
    })
    if len(viable) >= 2 and viable[0].score - viable[1].score <= 15:
        cases.append(_review(
            profile_id, media.anilist_id, MatchingReviewType.AMBIGUOUS_STRONG_CANDIDATES,
            ReviewSeverity.BLOCKING,
            ("Two server candidates have similarly strong evidence.",),
            tuple(item.candidate_id for item in viable[:8]), (), now,
            identity_basis=tuple(item.target.identity_key for item in viable[:8]),
        ))

    targets = {mapping.target.identity_key for mapping in media_mappings}
    if len(targets) > 1:
        cases.append(_review(
            profile_id, media.anilist_id, MatchingReviewType.CONFLICTING_ACTIVE_MAPPINGS,
            ReviewSeverity.BLOCKING,
            ("One AniList identity has conflicting active server targets.",),
            (), tuple(mapping.mapping_id for mapping in media_mappings), now,
        ))

    claims: dict[str, set[int]] = {}
    claim_mappings: dict[str, list[str]] = {}
    for mapping in mappings:
        if mapping.target.season_number is None:
            continue
        claims.setdefault(mapping.target.identity_key, set()).add(mapping.anilist_id)
        claim_mappings.setdefault(mapping.target.identity_key, []).append(mapping.mapping_id)
    for identity, owners in sorted(claims.items()):
        if len(owners) > 1:
            cases.append(_review(
                profile_id, media.anilist_id, MatchingReviewType.DUPLICATE_SEASON_CLAIM,
                ReviewSeverity.BLOCKING,
                ("Multiple AniList identities claim the same exact season scope.",),
                (), tuple(sorted(claim_mappings[identity])), now,
            ))

    for mapping_id in missing_paths:
        cases.append(_review(
            profile_id, media.anilist_id, MatchingReviewType.MISSING_CONFIRMED_PATH,
            ReviewSeverity.BLOCKING, ("A confirmed server path is missing.",), (), (mapping_id,), now,
        ))
    for mapping_id in missing_seasons:
        cases.append(_review(
            profile_id, media.anilist_id, MatchingReviewType.MISSING_CONFIRMED_SEASON,
            ReviewSeverity.BLOCKING, ("The confirmed series folder exists but its mapped season is missing.",),
            (), (mapping_id,), now,
        ))

    if any(mapping.confirmation_state == ConfirmationState.CONFIRMED and mapping.target.target_type.value == "UNKNOWN_TARGET" for mapping in media_mappings):
        cases.append(_review(
            profile_id, media.anilist_id, MatchingReviewType.LEGACY_SEASON_SCOPE_UNKNOWN,
            ReviewSeverity.BLOCKING, ("A confirmed legacy folder mapping has no explicit season scope.",),
            (), tuple(mapping.mapping_id for mapping in media_mappings if mapping.target.target_type.value == "UNKNOWN_TARGET"), now,
        ))

    if candidates and any(item.evidence.absolute_numbering for item in candidates):
        cases.append(_review(
            profile_id, media.anilist_id, MatchingReviewType.ABSOLUTE_NUMBERING_UNRESOLVED,
            ReviewSeverity.BLOCKING,
            ("Absolute episode numbers cannot be converted to season episodes automatically.",),
            tuple(item.candidate_id for item in candidates if item.evidence.absolute_numbering), (), now,
            identity_basis=tuple(item.target.identity_key for item in candidates if item.evidence.absolute_numbering),
        ))

    unstable = tuple(
        item for item in candidates
        if any("changed stable inventory identity" in warning for warning in item.evidence.warnings)
    )
    if unstable:
        cases.append(_review(
            profile_id, media.anilist_id, MatchingReviewType.UNSTABLE_REJECTED_TARGET,
            ReviewSeverity.BLOCKING,
            ("A rejected target reappeared through a changed inventory identity.",),
            tuple(item.candidate_id for item in unstable), (), now,
            identity_basis=tuple(item.target.normalized_path for item in unstable),
        ))

    if media.media_format in {MediaKind.OVA, MediaKind.ONA, MediaKind.SPECIAL} and candidates and not any(mapping.is_confirmed for mapping in media_mappings):
        cases.append(_review(
            profile_id, media.anilist_id, MatchingReviewType.SPECIAL_PARENT_UNRESOLVED,
            ReviewSeverity.BLOCKING,
            ("OVA, ONA, or special server scope requires manual confirmation.",),
            tuple(item.candidate_id for item in candidates), (), now,
            identity_basis=tuple(item.target.identity_key for item in candidates),
        ))

    if media.media_format == MediaKind.MOVIE and any(mapping.target.library_kind.value == "TV" for mapping in media_mappings):
        cases.append(_review(
            profile_id, media.anilist_id, MatchingReviewType.MOVIE_SERIES_CONFLICT,
            ReviewSeverity.BLOCKING, ("A movie is mapped to TV inventory and requires explicit review.",),
            (), tuple(mapping.mapping_id for mapping in media_mappings), now,
        ))

    unique = {case.review_id: case for case in cases}
    return tuple(sorted(unique.values(), key=lambda item: item.review_id))


def addressed_review_types_for_target(target_type: str) -> tuple[MatchingReviewType, ...]:
    values = [
        MatchingReviewType.AMBIGUOUS_STRONG_CANDIDATES,
        MatchingReviewType.MISSING_CONFIRMED_PATH,
        MatchingReviewType.MISSING_CONFIRMED_SEASON,
        MatchingReviewType.LEGACY_SEASON_SCOPE_UNKNOWN,
        MatchingReviewType.INVENTORY_IDENTITY_CHANGED,
    ]
    if target_type in {"SERIES_SPECIALS", "SEPARATE_SERIES", "MOVIE_ITEM"}:
        values.append(MatchingReviewType.SPECIAL_PARENT_UNRESOLVED)
    return tuple(values)


def _review(
    profile_id: str,
    anilist_id: int,
    review_type: MatchingReviewType,
    severity: ReviewSeverity,
    evidence: tuple[str, ...],
    candidate_ids: tuple[str, ...],
    mapping_ids: tuple[str, ...],
    now: datetime,
    identity_basis: tuple[str, ...] = (),
) -> MatchingReviewCase:
    basis = "|".join((
        profile_id, str(anilist_id), review_type.value,
        *sorted(identity_basis or candidate_ids), *sorted(mapping_ids),
    ))
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    return MatchingReviewCase(
        f"review-{digest}", profile_id, anilist_id, review_type, ReviewCaseState.OPEN,
        severity, evidence, candidate_ids, mapping_ids, now, now,
    )
