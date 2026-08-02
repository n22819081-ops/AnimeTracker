from __future__ import annotations

from datetime import datetime

from ...domain.coverage import calculate_episode_coverage, determine_server_presence
from ...domain.enums import ConfidenceLevel, CoverageSource, MediaKind, ServerPresence
from ...domain.models import AniListMediaIdentity, MediaTitle
from ..anilist.models import AniListMedia
from ..server_inventory.models import InventoryLibraryItem, ServerInventorySnapshot
from .models import (
    MappingCoverageEvaluation,
    MappingTargetType,
    MatchingReviewCase,
    MatchingReviewType,
    PersistentMapping,
    ReviewCaseState,
    ReviewSeverity,
)


def evaluate_mapping_coverage(
    mapping: PersistentMapping,
    media: AniListMedia,
    snapshot: ServerInventorySnapshot,
    *,
    aired_episode_count: int | None,
    now: datetime,
) -> MappingCoverageEvaluation:
    item, identity_changed = _find_item(mapping, snapshot)
    identity = _identity(media)
    if item is None:
        review = _coverage_review(mapping, MatchingReviewType.MISSING_CONFIRMED_PATH, "Confirmed inventory item is missing.", now)
        return MappingCoverageEvaluation(mapping, ServerPresence.PATH_MISSING, None, (review,))

    identity_reviews: tuple[MatchingReviewCase, ...] = ()
    if identity_changed:
        identity_reviews = (_coverage_review(
            mapping,
            MatchingReviewType.INVENTORY_IDENTITY_CHANGED,
            "The normalized path remains present but its stable inventory identity changed.",
            now,
        ),)

    target = mapping.target
    if target.target_type == MappingTargetType.MOVIE_ITEM:
        state = determine_server_presence(
            identity,
            mapping_confirmed=True,
            path_exists=True,
            movie_item_present=bool(item.movie_files),
        )
        return MappingCoverageEvaluation(mapping, state.presence, state.coverage, identity_reviews)

    if target.target_type == MappingTargetType.UNKNOWN_TARGET:
        review_type = MatchingReviewType.ABSOLUTE_NUMBERING_UNRESOLVED if any(
            file.absolute_episode_numbers for file in item.unrecognized_media
        ) else MatchingReviewType.LEGACY_SEASON_SCOPE_UNKNOWN
        review = _coverage_review(mapping, review_type, "Confirmed mapping has no reliable season scope.", now)
        return MappingCoverageEvaluation(mapping, ServerPresence.UNKNOWN_COVERAGE, None, (*identity_reviews, review))

    present: list[int | None] = []
    special_numbers: list[int] = []
    if target.target_type == MappingTargetType.SERIES_SPECIALS or target.season_number == 0:
        files = tuple(file for group in item.specials for file in group.files)
        present.extend(number for file in files for number in file.episode_numbers)
        special_numbers.extend(number for file in files for number in file.episode_numbers)
    elif target.target_type == MappingTargetType.SERIES_SEASON:
        season = next((value for value in item.seasons if value.season_number == target.season_number), None)
        if season is None:
            review = _coverage_review(
                mapping, MatchingReviewType.MISSING_CONFIRMED_SEASON,
                f"Confirmed Season {target.season_number} is missing from the series folder.", now,
            )
            return MappingCoverageEvaluation(mapping, ServerPresence.PATH_MISSING, None, (*identity_reviews, review))
        present.extend(number for file in season.files for number in file.episode_numbers)
    elif target.target_type == MappingTargetType.SEPARATE_SERIES:
        present.extend(number for season in item.seasons for file in season.files for number in file.episode_numbers)
        present.extend(number for group in item.specials for file in group.files for number in file.episode_numbers)
        if not present and any(file.absolute_episode_numbers for file in item.unrecognized_media):
            review = _coverage_review(
                mapping, MatchingReviewType.ABSOLUTE_NUMBERING_UNRESOLVED,
                "Separate series uses unresolved absolute numbering.", now,
            )
            return MappingCoverageEvaluation(mapping, ServerPresence.UNKNOWN_COVERAGE, None, (*identity_reviews, review))
    else:
        return MappingCoverageEvaluation(mapping, ServerPresence.UNKNOWN_COVERAGE, None, identity_reviews)

    coverage = calculate_episode_coverage(
        expected_total_episodes=media.episode_count,
        aired_episode_count=aired_episode_count,
        present_episode_numbers=present,
        special_episode_numbers=special_numbers,
        coverage_source=CoverageSource.FILESYSTEM,
        coverage_calculated_at=now,
        confidence=ConfidenceLevel.CONFIRMED,
    )
    state = determine_server_presence(
        identity,
        mapping_confirmed=True,
        path_exists=True,
        coverage=coverage,
        special_mapping_resolved=True,
    )
    return MappingCoverageEvaluation(mapping, state.presence, coverage, identity_reviews, coverage.warnings)


def _find_item(mapping: PersistentMapping, snapshot: ServerInventorySnapshot) -> tuple[InventoryLibraryItem | None, bool]:
    exact = next((item for item in snapshot.items if item.item_id == mapping.target.inventory_item_id), None)
    if exact:
        return exact, False
    by_path = next((item for item in snapshot.items if item.normalized_path == mapping.target.normalized_path), None)
    return by_path, by_path is not None


def _identity(media: AniListMedia) -> AniListMediaIdentity:
    return AniListMediaIdentity(
        media.anilist_id,
        MediaTitle(media.title.english, media.title.romaji, media.title.native, media.title.synonyms),
        media.media_format,
        media.status,
        media.season,
        media.season_year,
        media.episode_count,
        media.start_date.isoformat() if media.start_date else "",
        media.end_date.isoformat() if media.end_date else "",
        media.site_url,
        media.cover_images.large,
    )


def _coverage_review(
    mapping: PersistentMapping,
    review_type: MatchingReviewType,
    evidence: str,
    now: datetime,
) -> MatchingReviewCase:
    return MatchingReviewCase(
        f"review-{mapping.mapping_id}-{review_type.value.casefold()}", mapping.profile_id,
        mapping.anilist_id, review_type, ReviewCaseState.OPEN, ReviewSeverity.BLOCKING,
        (evidence,), (), (mapping.mapping_id,), now, now,
    )
