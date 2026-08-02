from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from anime_tracker.domain.coverage import determine_server_presence
from anime_tracker.domain.enums import AniListStatus, LibraryKind, MediaKind, ServerPresence, TrackingContentKind
from anime_tracker.domain.models import AniListMediaIdentity, MediaTitle
from anime_tracker.modernization.schema_v4 import initialize_matching_test_database
from anime_tracker.services.matching import (
    ConfirmationState,
    MappingSource,
    MappingTarget,
    MappingTargetType,
    MatchConfidence,
    MatchingRepository,
    MatchingReviewCase,
    MatchingReviewType,
    MatchingService,
    PathState,
    PersistentMapping,
    ReviewCaseState,
    ReviewSeverity,
)
from anime_tracker.services.matching.candidates import generate_match_candidates, inventory_snapshot_id, media_version
from anime_tracker.services.matching.coverage import evaluate_mapping_coverage
from anime_tracker.services.matching.models import MatchingSession
from anime_tracker.services.matching.reviews import generate_matching_reviews
from anime_tracker.services.server_inventory.models import SpecialKind

from matching_helpers import NOW, episode_file, inventory_item, media, snapshot


def candidate_result(media_value, inventory, key="s"):
    session = MatchingSession(key, "default", inventory_snapshot_id(inventory), media_version(media_value), NOW, NOW)
    return generate_match_candidates(media_value, inventory, session)


def mapping_for(media_value, target, mapping_id="mapping", profile="default"):
    return PersistentMapping(
        mapping_id, profile, media_value.anilist_id, target, MappingSource.MANUAL_CONFIRMATION,
        ConfirmationState.CONFIRMED, MatchConfidence.VERY_STRONG, NOW, NOW,
    )


class ReviewRuleTests(unittest.TestCase):
    def test_no_review_for_empty_candidate_list(self):
        value = media()
        generated = candidate_result(value, snapshot())
        reviews = generate_matching_reviews(profile_id="default", media=value, generated=generated, mappings=(), now=NOW)
        self.assertEqual(reviews, ())

    def test_equal_strong_candidates_create_ambiguity(self):
        value = media()
        generated = candidate_result(value, snapshot(
            inventory_item(item_id="one"), inventory_item(item_id="two"),
        ))
        reviews = generate_matching_reviews(profile_id="default", media=value, generated=generated, mappings=(), now=NOW)
        self.assertIn(MatchingReviewType.AMBIGUOUS_STRONG_CANDIDATES, {review.review_type for review in reviews})

    def test_conflicting_active_mappings_create_review(self):
        value = media()
        first = candidate_result(value, snapshot(inventory_item(item_id="one"))).candidates[0].target
        second = candidate_result(value, snapshot(inventory_item(item_id="two"))).candidates[0].target
        reviews = generate_matching_reviews(
            profile_id="default", media=value, generated=None,
            mappings=(mapping_for(value, first, "one"), mapping_for(value, second, "two")), now=NOW,
        )
        self.assertIn(MatchingReviewType.CONFLICTING_ACTIVE_MAPPINGS, {review.review_type for review in reviews})

    def test_two_anilist_ids_claiming_exact_season_create_review(self):
        value = media()
        target = candidate_result(value, snapshot(inventory_item())).candidates[0].target
        mappings = (mapping_for(value, target, "one"), mapping_for(media(anilist_id=200), target, "two"))
        reviews = generate_matching_reviews(profile_id="default", media=value, generated=None, mappings=mappings, now=NOW)
        self.assertIn(MatchingReviewType.DUPLICATE_SEASON_CLAIM, {review.review_type for review in reviews})

    def test_legacy_mapping_without_season_scope_creates_review(self):
        value = media()
        target = MappingTarget(
            MappingTargetType.UNKNOWN_TARGET, LibraryKind.TV, "TV", "Example", "x:\\example",
            "legacy-item", None, TrackingContentKind.SERIES, "legacy", "Example", PathState.UNKNOWN,
        )
        reviews = generate_matching_reviews(
            profile_id="default", media=value, generated=None,
            mappings=(mapping_for(value, target),), now=NOW,
        )
        self.assertIn(MatchingReviewType.LEGACY_SEASON_SCOPE_UNKNOWN, {review.review_type for review in reviews})

    def test_another_titles_legacy_mapping_does_not_create_review(self):
        value = media(anilist_id=200)
        owner = media(anilist_id=100)
        target = MappingTarget(
            MappingTargetType.UNKNOWN_TARGET, LibraryKind.TV, "TV", "Example", "x:\\example",
            "legacy-item", None, TrackingContentKind.SERIES, "legacy", "Example", PathState.UNKNOWN,
        )
        reviews = generate_matching_reviews(
            profile_id="default", media=value, generated=None,
            mappings=(mapping_for(owner, target),), now=NOW,
        )
        self.assertNotIn(MatchingReviewType.LEGACY_SEASON_SCOPE_UNKNOWN, {review.review_type for review in reviews})

    def test_movie_mapped_to_tv_creates_conflict_review(self):
        value = media("Example Movie", kind=MediaKind.MOVIE)
        target = MappingTarget(
            MappingTargetType.SERIES_FOLDER, LibraryKind.TV, "TV", "Example", "x:\\example",
            "tv-item", None, TrackingContentKind.MOVIE, "snapshot", "Example", PathState.EXISTS,
        )
        reviews = generate_matching_reviews(
            profile_id="default", media=value, generated=None, mappings=(mapping_for(value, target),), now=NOW,
        )
        self.assertIn(MatchingReviewType.MOVIE_SERIES_CONFLICT, {review.review_type for review in reviews})

    def test_special_candidate_requires_parent_review_but_no_candidate_does_not(self):
        value = media("Example Anime OVA", kind=MediaKind.OVA, episodes=1)
        generated = candidate_result(value, snapshot(inventory_item(specials=((SpecialKind.OVA, (1,)),))))
        reviews = generate_matching_reviews(profile_id="default", media=value, generated=generated, mappings=(), now=NOW)
        self.assertIn(MatchingReviewType.SPECIAL_PARENT_UNRESOLVED, {review.review_type for review in reviews})
        empty = generate_matching_reviews(
            profile_id="default", media=value, generated=candidate_result(value, snapshot()), mappings=(), now=NOW,
        )
        self.assertEqual(empty, ())

    def test_absolute_numbering_requires_episode_mapping_review(self):
        value = media()
        absolute = episode_file("absolute", 1, 13, absolute=True, name="13 - Next Arc.mkv")
        generated = candidate_result(value, snapshot(inventory_item(seasons={}, unrecognized=(absolute,))))
        reviews = generate_matching_reviews(profile_id="default", media=value, generated=generated, mappings=(), now=NOW)
        self.assertIn(MatchingReviewType.ABSOLUTE_NUMBERING_UNRESOLVED, {review.review_type for review in reviews})


class CoverageScopeTests(unittest.TestCase):
    def item_and_targets(self):
        item = inventory_item(
            seasons={1: range(1, 13), 2: range(1, 4)},
            specials=((SpecialKind.OVA, (1,)),),
        )
        inventory = snapshot(item)
        season_one_media = media("Example Anime Season 1", anilist_id=100, episodes=12)
        season_two_media = media(
            "Example Anime Season 2", anilist_id=200, episodes=12, status=AniListStatus.RELEASING,
        )
        ova_media = media("Example Anime OVA", anilist_id=300, kind=MediaKind.OVA, episodes=1)
        one = candidate_result(season_one_media, inventory, "one").candidates[0].target
        two = candidate_result(season_two_media, inventory, "two").candidates[0].target
        ova = candidate_result(ova_media, inventory, "ova").candidates[0].target
        return inventory, season_one_media, season_two_media, ova_media, one, two, ova

    def test_many_to_one_targets_preserve_three_distinct_scopes(self):
        _, one_media, two_media, ova_media, one, two, ova = self.item_and_targets()
        mappings = (
            mapping_for(one_media, one, "one"), mapping_for(two_media, two, "two"), mapping_for(ova_media, ova, "ova"),
        )
        self.assertEqual({mapping.target.inventory_item_id for mapping in mappings}, {"item-example"})
        self.assertEqual({mapping.target.season_number for mapping in mappings}, {0, 1, 2})

    def test_coverage_is_calculated_independently_for_each_scope(self):
        inventory, one_media, two_media, ova_media, one, two, ova = self.item_and_targets()
        one_result = evaluate_mapping_coverage(mapping_for(one_media, one, "one"), one_media, inventory, aired_episode_count=12, now=NOW)
        two_result = evaluate_mapping_coverage(mapping_for(two_media, two, "two"), two_media, inventory, aired_episode_count=3, now=NOW)
        ova_result = evaluate_mapping_coverage(mapping_for(ova_media, ova, "ova"), ova_media, inventory, aired_episode_count=1, now=NOW)
        self.assertEqual(one_result.coverage.present_episode_numbers, frozenset(range(1, 13)))
        self.assertEqual(two_result.coverage.present_episode_numbers, frozenset({1, 2, 3}))
        self.assertEqual(ova_result.coverage.present_episode_numbers, frozenset({1}))
        self.assertEqual((one_result.server_presence, two_result.server_presence, ova_result.server_presence), (
            ServerPresence.COMPLETE, ServerPresence.COMPLETE, ServerPresence.COMPLETE,
        ))

    def test_season_one_presence_cannot_satisfy_season_two(self):
        inventory, _, two_media, _, _, two, _ = self.item_and_targets()
        without_two = snapshot(inventory_item(seasons={1: range(1, 13)}))
        result = evaluate_mapping_coverage(mapping_for(two_media, two, "two"), two_media, without_two, aired_episode_count=3, now=NOW)
        self.assertEqual(result.server_presence, ServerPresence.PATH_MISSING)
        self.assertEqual(result.review_cases[0].review_type, MatchingReviewType.MISSING_CONFIRMED_SEASON)

    def test_shared_folder_itself_does_not_imply_coverage(self):
        value = media()
        inventory = snapshot(inventory_item(seasons={}))
        target = candidate_result(value, inventory).candidates[0].target
        result = evaluate_mapping_coverage(mapping_for(value, target), value, inventory, aired_episode_count=12, now=NOW)
        self.assertEqual(result.server_presence, ServerPresence.UNKNOWN_COVERAGE)

    def test_missing_confirmed_item_is_path_missing(self):
        value = media()
        present = snapshot(inventory_item())
        target = candidate_result(value, present).candidates[0].target
        result = evaluate_mapping_coverage(mapping_for(value, target), value, snapshot(), aired_episode_count=12, now=NOW)
        self.assertEqual(result.server_presence, ServerPresence.PATH_MISSING)
        self.assertEqual(result.review_cases[0].review_type, MatchingReviewType.MISSING_CONFIRMED_PATH)

    def test_movie_requires_exact_movie_item_file(self):
        value = media("Example Movie", kind=MediaKind.MOVIE)
        movie_item = inventory_item("Example Movie (2024)", item_id="movie", movie=True, kind=LibraryKind.MOVIE, root="Movies")
        inventory = snapshot(movie_item)
        target = candidate_result(value, inventory).candidates[0].target
        result = evaluate_mapping_coverage(mapping_for(value, target), value, inventory, aired_episode_count=None, now=NOW)
        self.assertEqual(result.server_presence, ServerPresence.COMPLETE)

    def test_no_confirmed_mapping_remains_normal_not_found(self):
        identity = AniListMediaIdentity(100, MediaTitle("Example"), MediaKind.TV)
        state = determine_server_presence(identity, mapping_confirmed=False)
        self.assertEqual(state.presence, ServerPresence.NOT_FOUND)


class MatchingServiceReviewLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "matching.db"
        initialize_matching_test_database(self.db)
        self.repo = MatchingRepository(self.db)
        self.service = MatchingService(self.repo, clock=lambda: NOW)

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_mapping_is_marked_broken_and_not_replaced(self):
        value = media()
        original = snapshot(inventory_item())
        generated = self.service.generate_candidates(value, original, session_id="original")
        mapping = self.service.confirm_mapping(generated.candidates[0].candidate_id, value, original)
        results = self.service.check_confirmed_mappings(value, snapshot(), aired_episode_count=12)
        self.assertEqual(results[0].server_presence, ServerPresence.PATH_MISSING)
        stored = self.repo.list_mappings("default", value.anilist_id)[0]
        self.assertEqual(stored.confirmation_state, ConfirmationState.BROKEN)
        alternative = snapshot(inventory_item("Example Anime Alternate (2024)", item_id="alternative"))
        candidates = self.service.generate_candidates(value, alternative, session_id="alternative")
        self.assertFalse(any(candidate.preselected for candidate in candidates.candidates))
        self.assertEqual(self.repo.list_mappings("default", value.anilist_id)[0].mapping_id, mapping.mapping_id)

    def test_three_identities_persist_to_one_item_with_distinct_scopes(self):
        item = inventory_item(
            seasons={1: range(1, 13), 2: range(1, 13)},
            specials=((SpecialKind.OVA, (1,)),),
        )
        inventory = snapshot(item)
        values = (
            media("Example Anime Season 1", anilist_id=100),
            media("Example Anime Season 2", anilist_id=200),
            media("Example Anime OVA", anilist_id=300, kind=MediaKind.OVA, episodes=1),
        )
        mappings = []
        for index, value in enumerate(values):
            generated = self.service.generate_candidates(value, inventory, session_id=f"scope-{index}")
            mappings.append(self.service.create_manual_mapping(value.anilist_id, generated.candidates[0].target))
        stored = self.repo.list_all_active_mappings("default")
        self.assertEqual(len(stored), 3)
        self.assertEqual({mapping.target.inventory_item_id for mapping in stored}, {"item-example"})
        self.assertEqual({mapping.target.season_number for mapping in stored}, {0, 1, 2})

    def test_relevant_confirmation_resolves_only_addressed_reviews(self):
        value = media()
        inventory = snapshot(inventory_item())
        generated = self.service.generate_candidates(value, inventory, session_id="confirm")
        addressed = MatchingReviewCase(
            "addressed", "default", value.anilist_id, MatchingReviewType.AMBIGUOUS_STRONG_CANDIDATES,
            ReviewCaseState.OPEN, ReviewSeverity.BLOCKING, ("ambiguous",),
            (generated.candidates[0].candidate_id,), (), NOW, NOW,
        )
        unrelated = replace(
            addressed,
            review_id="unrelated",
            review_type=MatchingReviewType.DUPLICATE_SEASON_CLAIM,
            evidence=("duplicate",),
        )
        self.repo.save_review(addressed)
        self.repo.save_review(unrelated)
        self.service.confirm_mapping(generated.candidates[0].candidate_id, value, inventory)
        all_reviews = self.repo.list_reviews("default", anilist_id=value.anilist_id, open_only=False)
        states = {review.review_id: review.state for review in all_reviews}
        self.assertEqual(states["addressed"], ReviewCaseState.RESOLVED)
        self.assertEqual(states["unrelated"], ReviewCaseState.OPEN)

    def test_review_resolution_is_profile_scoped(self):
        review = MatchingReviewCase(
            "profile-review", "one", 100, MatchingReviewType.AMBIGUOUS_STRONG_CANDIDATES,
            ReviewCaseState.OPEN, ReviewSeverity.BLOCKING, ("ambiguous",), (), (), NOW, NOW,
        )
        self.repo.save_review(review)
        with self.assertRaises(KeyError):
            self.service.resolve_review("profile-review", "wrong profile", profile_id="two")
        self.assertEqual(self.repo.list_reviews("one")[0].state, ReviewCaseState.OPEN)

    def test_acknowledge_dismiss_and_supersede_review_lifecycle(self):
        base = MatchingReviewCase(
            "lifecycle", "default", 100, MatchingReviewType.AMBIGUOUS_STRONG_CANDIDATES,
            ReviewCaseState.OPEN, ReviewSeverity.BLOCKING, ("ambiguous",), (), (), NOW, NOW,
        )
        self.repo.save_review(base)
        self.service.acknowledge_review("lifecycle", user_note="seen")
        self.assertEqual(self.repo.list_reviews("default", open_only=False)[0].state, ReviewCaseState.ACKNOWLEDGED)
        self.service.resolve_review("lifecycle", "not applicable", dismiss=True)
        self.assertEqual(self.repo.list_reviews("default", open_only=False)[0].state, ReviewCaseState.DISMISSED)
        second = replace(base, review_id="superseded")
        self.repo.save_review(second)
        self.service.supersede_review("superseded", resolution="newer case")
        states = {review.review_id: review.state for review in self.repo.list_reviews("default", open_only=False)}
        self.assertEqual(states["superseded"], ReviewCaseState.SUPERSEDED)

    def test_repeated_ambiguity_regeneration_reuses_review_identity(self):
        value = media()
        inventory = snapshot(inventory_item(item_id="one"), inventory_item(item_id="two"))
        first = self.service.generate_candidates(value, inventory, session_id="ambiguity-one")
        second = self.service.generate_candidates(value, inventory, session_id="ambiguity-two")
        reviews = self.repo.list_reviews("default", anilist_id=value.anilist_id)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0].review_type, MatchingReviewType.AMBIGUOUS_STRONG_CANDIDATES)
        self.assertNotEqual(first.candidates[0].candidate_id, second.candidates[0].candidate_id)

    def test_changed_inventory_identity_creates_review_without_replacing_mapping(self):
        value = media()
        original = snapshot(inventory_item(item_id="old-stable-id"))
        generated = self.service.generate_candidates(value, original, session_id="identity-original")
        mapping = self.service.confirm_mapping(generated.candidates[0].candidate_id, value, original)
        changed = snapshot(inventory_item(item_id="new-stable-id"))
        result = self.service.check_confirmed_mappings(value, changed, aired_episode_count=12)[0]
        self.assertIn(
            MatchingReviewType.INVENTORY_IDENTITY_CHANGED,
            {review.review_type for review in result.review_cases},
        )
        self.assertEqual(self.repo.list_mappings("default", value.anilist_id)[0].mapping_id, mapping.mapping_id)


if __name__ == "__main__":
    unittest.main()
