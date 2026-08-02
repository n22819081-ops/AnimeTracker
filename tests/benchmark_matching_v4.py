"""Reproducible synthetic Milestone 5 performance baseline.

This module deliberately constructs inventory models in memory. It does not scan
the filesystem, open a database, or call a provider.
"""

from __future__ import annotations

import json
import statistics
import time

from matching_helpers import NOW, inventory_item, media, snapshot

from anime_tracker.domain.enums import AniListStatus, MediaKind
from anime_tracker.services.server_inventory.models import SpecialKind
from anime_tracker.services.matching.candidates import (
    generate_match_candidates,
    inventory_snapshot_id,
    media_version,
)
from anime_tracker.services.matching.coverage import evaluate_mapping_coverage
from anime_tracker.services.matching.models import (
    ConfirmationState,
    MappingSource,
    MatchConfidence,
    MatchingRejection,
    MatchingRejectionScope,
    MatchingSession,
    PersistentMapping,
)
from anime_tracker.services.matching.reviews import generate_matching_reviews


def _measure(operation, repetitions: int) -> float:
    samples = []
    for _ in range(repetitions):
        started = time.perf_counter()
        operation()
        samples.append((time.perf_counter() - started) * 1000)
    return statistics.median(samples)


def _generate(value, inventory, session_id="benchmark", *, rejections=(), mappings=()):
    session = MatchingSession(
        session_id,
        "benchmark",
        inventory_snapshot_id(inventory),
        media_version(value),
        NOW,
    )
    return generate_match_candidates(
        value, inventory, session, rejections=rejections, mappings=mappings,
    )


def main() -> None:
    one_media = media()
    one_inventory = snapshot(inventory_item())
    one_result = _generate(one_media, one_inventory)
    candidate = one_result.candidates[0]
    rejection = MatchingRejection(
        "benchmark-rejection", "benchmark", one_media.anilist_id,
        MatchingRejectionScope.EXACT_TARGET, candidate.target.identity_key,
        "benchmark", NOW,
    )

    representative_items = tuple(
        inventory_item(f"Synthetic Anime {index} (2024)", item_id=f"item-{index}")
        for index in range(69)
    )
    representative_inventory = snapshot(*representative_items)
    representative_media = tuple(
        media(f"Synthetic Anime {index}", anilist_id=10_000 + index)
        for index in range(69)
    )

    large_inventory = snapshot(inventory_item(seasons={1: range(1, 4_801)}))
    shared_inventory = snapshot(inventory_item(
        seasons={1: range(1, 13), 2: range(1, 4)},
        specials=((SpecialKind.OVA, (1,)),),
    ))
    scoped_media = (
        media("Example Anime Season 1", anilist_id=100),
        media(
            "Example Anime Season 2", anilist_id=200, status=AniListStatus.RELEASING,
        ),
        media("Example Anime OVA", anilist_id=300, kind=MediaKind.OVA, episodes=1),
    )
    scoped_mappings = tuple(
        PersistentMapping(
            f"benchmark-mapping-{value.anilist_id}", "benchmark", value.anilist_id,
            _generate(value, shared_inventory, f"scope-{value.anilist_id}").candidates[0].target,
            MappingSource.MANUAL_CONFIRMATION, ConfirmationState.CONFIRMED,
            MatchConfidence.VERY_STRONG, NOW, NOW,
        )
        for value in scoped_media
    )

    results = {
        "one_entry_ms_median": _measure(lambda: _generate(one_media, one_inventory), 25),
        "all_69_entries_ms_median": _measure(
            lambda: [
                _generate(value, representative_inventory, f"all-{value.anilist_id}")
                for value in representative_media
            ],
            5,
        ),
        "inventory_4800_files_ms_median": _measure(
            lambda: _generate(one_media, large_inventory, "large"), 7,
        ),
        "rejection_filter_ms_median": _measure(
            lambda: _generate(one_media, one_inventory, "rejected", rejections=(rejection,)), 25,
        ),
        "review_generation_ms_median": _measure(
            lambda: generate_matching_reviews(
                profile_id="benchmark", media=one_media, generated=one_result,
                mappings=(), now=NOW,
            ),
            100,
        ),
        "many_to_one_coverage_ms_median": _measure(
            lambda: [
                evaluate_mapping_coverage(
                    mapping, value, shared_inventory,
                    aired_episode_count=3 if value.anilist_id == 200 else value.episode_count,
                    now=NOW,
                )
                for mapping, value in zip(scoped_mappings, scoped_media)
            ],
            100,
        ),
    }
    print(json.dumps({key: round(value, 4) for key, value in results.items()}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
