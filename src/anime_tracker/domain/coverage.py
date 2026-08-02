from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Iterable

from .enums import AniListStatus, ConfidenceLevel, CoverageSource, MediaKind, ServerPresence
from .models import AniListMediaIdentity, EpisodeCoverage, ServerPresenceState


def calculate_episode_coverage(
    *,
    expected_total_episodes: int | None,
    aired_episode_count: int | None,
    present_episode_numbers: Iterable[int | None],
    special_episode_numbers: Iterable[int] = (),
    coverage_source: CoverageSource = CoverageSource.UNKNOWN,
    coverage_calculated_at: datetime | None = None,
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN,
) -> EpisodeCoverage:
    """Normalize episode evidence without interpreting a folder as completeness."""
    raw_numbers = tuple(present_episode_numbers)
    values = tuple(number for number in raw_numbers if isinstance(number, int) and number > 0)
    unknown_count = sum(1 for number in raw_numbers if not isinstance(number, int) or number <= 0)
    counts = Counter(values)
    present = frozenset(values)
    duplicates = frozenset(number for number, count in counts.items() if count > 1)
    aired_required = frozenset(range(1, aired_episode_count + 1)) if aired_episode_count is not None and aired_episode_count > 0 else frozenset()
    expected_required = frozenset(range(1, expected_total_episodes + 1)) if expected_total_episodes is not None and expected_total_episodes > 0 else frozenset()
    warnings: list[str] = []
    if duplicates:
        warnings.append("Duplicate episode numbers were observed.")
    if unknown_count:
        warnings.append("Some files had no reliable episode number.")
    if expected_total_episodes is not None and any(number > expected_total_episodes for number in present):
        warnings.append("Episode numbers above the expected total were observed.")
    if aired_episode_count is not None and expected_total_episodes is not None and aired_episode_count > expected_total_episodes:
        warnings.append("Aired episode count exceeds the provider's expected total.")
    return EpisodeCoverage(
        expected_total_episodes=expected_total_episodes,
        aired_episode_count=aired_episode_count,
        present_episode_numbers=present,
        missing_aired_episode_numbers=aired_required - present,
        missing_expected_episode_numbers=expected_required - present,
        duplicate_episode_numbers=duplicates,
        unknown_numbered_files=unknown_count,
        special_episode_numbers=frozenset(number for number in special_episode_numbers if number >= 0),
        coverage_source=coverage_source,
        coverage_calculated_at=coverage_calculated_at,
        confidence=confidence,
        warnings=tuple(warnings),
    )


def determine_server_presence(
    identity: AniListMediaIdentity,
    *,
    mapping_confirmed: bool,
    path_exists: bool | None = None,
    coverage: EpisodeCoverage | None = None,
    movie_item_present: bool = False,
    special_mapping_resolved: bool = True,
) -> ServerPresenceState:
    if not mapping_confirmed:
        return ServerPresenceState(ServerPresence.NOT_FOUND, coverage, False, path_exists, "NO_CONFIRMED_MAPPING")
    if path_exists is False:
        return ServerPresenceState(ServerPresence.PATH_MISSING, coverage, True, False, "CONFIRMED_PATH_MISSING")
    if identity.media_kind == MediaKind.MOVIE:
        presence = ServerPresence.COMPLETE if movie_item_present else ServerPresence.NOT_FOUND
        code = "CONFIRMED_MOVIE_PRESENT" if movie_item_present else "CONFIRMED_MOVIE_NOT_PRESENT"
        return ServerPresenceState(presence, coverage, True, path_exists, code)
    if identity.media_kind in {MediaKind.SPECIAL, MediaKind.OVA, MediaKind.ONA} and not special_mapping_resolved:
        return ServerPresenceState(ServerPresence.UNKNOWN_COVERAGE, coverage, True, path_exists, "SPECIAL_MAPPING_UNRESOLVED")
    if coverage is None:
        return ServerPresenceState(ServerPresence.UNKNOWN_COVERAGE, None, True, path_exists, "NO_RELIABLE_EPISODE_INVENTORY")

    present = coverage.present_episode_numbers
    if identity.status in {AniListStatus.RELEASING, AniListStatus.HIATUS}:
        aired = coverage.aired_episode_count
        if aired is None:
            presence = ServerPresence.UNKNOWN_COVERAGE
            code = "AIRED_COUNT_UNKNOWN"
        elif aired <= 0 or not present.intersection(range(1, aired + 1)):
            presence = ServerPresence.NOT_FOUND
            code = "NO_AIRED_EPISODES_PRESENT"
        elif not coverage.missing_aired_episode_numbers:
            presence = ServerPresence.COMPLETE
            code = "ALL_AIRED_EPISODES_PRESENT"
        else:
            presence = ServerPresence.PARTIAL
            code = "SOME_AIRED_EPISODES_MISSING"
    elif identity.status == AniListStatus.FINISHED:
        expected = coverage.expected_total_episodes
        if expected is None or expected <= 0:
            presence = ServerPresence.UNKNOWN_COVERAGE
            code = "EXPECTED_EPISODE_COUNT_UNKNOWN"
        elif not present.intersection(range(1, expected + 1)):
            presence = ServerPresence.NOT_FOUND
            code = "NO_EXPECTED_EPISODES_PRESENT"
        elif not coverage.missing_expected_episode_numbers:
            presence = ServerPresence.COMPLETE
            code = "ALL_EXPECTED_EPISODES_PRESENT"
        else:
            presence = ServerPresence.PARTIAL
            code = "SOME_EXPECTED_EPISODES_MISSING"
    else:
        presence = ServerPresence.UNKNOWN_COVERAGE
        code = "STATUS_HAS_NO_COVERAGE_RULE"
    return ServerPresenceState(presence, coverage, True, path_exists, code, coverage.warnings)
