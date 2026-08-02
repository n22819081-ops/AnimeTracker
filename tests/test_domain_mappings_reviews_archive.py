from __future__ import annotations

import unittest
from dataclasses import replace

from anime_tracker.domain.archive import active_only, archive_tracked_media, restore_tracked_media
from anime_tracker.domain.enums import (
    ConfidenceLevel,
    LibraryKind,
    MappingConfirmation,
    MappingSource,
    MediaKind,
    OverrideType,
    RejectionScope,
    ReviewStatus,
    ServerPresence,
    TrackerWorkflowStatus,
    TrackingContentKind,
)
from anime_tracker.domain.mappings import is_candidate_rejected, mapping_fingerprint, validate_mappings
from anime_tracker.domain.models import (
    ArchiveBundle,
    ManualOverride,
    MatchCandidateEvidence,
    MediaServerMapping,
    RejectedMatchDecision,
    StatusTransition,
    TrackedMedia,
    JellyfinFolderMapping,
)
from anime_tracker.domain.overrides import suppresses_automatic_matching
from anime_tracker.domain.reviews import generate_review_cases

from domain_helpers import NOW, identity


def mapping(
    mapping_id="m1",
    anilist_id=1,
    path=r"I:\Shows\Example",
    season=1,
    content_kind=TrackingContentKind.SEASON,
    library=LibraryKind.TV,
    source=MappingSource.USER,
    **changes,
):
    item = MediaServerMapping(
        mapping_id, anilist_id, library, path, "jf-1", season, content_kind,
        MappingConfirmation.MANUAL, source, ConfidenceLevel.CONFIRMED,
    )
    return replace(item, **changes)


class MappingTests(unittest.TestCase):
    def test_one_anilist_id_to_one_folder(self):
        self.assertEqual(validate_mappings("1", (mapping(),)), ())

    def test_multiple_anilist_ids_can_share_one_folder(self):
        mappings = (mapping("m1", 1, season=1), mapping("m2", 2, season=2))
        self.assertEqual(validate_mappings("group", mappings), ())
        self.assertNotEqual(mapping_fingerprint(mappings), "")

    def test_season_two_maps_to_season_two(self):
        item = mapping(season=2)
        self.assertEqual(item.season_number, 2)
        self.assertEqual(item.content_kind, TrackingContentKind.SEASON)

    def test_special_can_be_confirmed_in_season_zero(self):
        item = JellyfinFolderMapping("jf-1", r"I:\Shows\Example", TrackingContentKind.SPECIAL, 0)
        self.assertEqual((item.content_kind, item.season_number), (TrackingContentKind.SPECIAL, 0))

    def test_ova_can_map_to_movies_or_separate_series(self):
        movie = mapping(content_kind=TrackingContentKind.OVA, library=LibraryKind.MOVIE, season=None)
        series = mapping("m2", content_kind=TrackingContentKind.OVA, library=LibraryKind.TV, season=None)
        self.assertEqual((movie.library_kind, series.library_kind), (LibraryKind.MOVIE, LibraryKind.TV))

    def test_season_one_scope_does_not_equal_season_two(self):
        one = mapping("m1", season=1)
        two = mapping("m2", season=2)
        self.assertNotEqual(mapping_fingerprint((one,)), mapping_fingerprint((two,)))

    def test_shared_path_distinct_entries_with_distinct_seasons_is_valid(self):
        cases = validate_mappings("shared", (mapping("m1", 1, season=1), mapping("m2", 2, season=2)))
        self.assertEqual(cases, ())

    def test_one_entry_conflicting_seasons_requires_review(self):
        cases = validate_mappings("1", (mapping("m1", 1, season=1), mapping("m2", 1, season=2)))
        self.assertIn(ReviewStatus.SEASON_MAPPING_REQUIRED, {case.status for case in cases})

    def test_multiple_targets_require_explicit_support(self):
        cases = validate_mappings("1", (mapping("m1"), mapping("m2", path=r"I:\Shows\Other")))
        self.assertIn(ReviewStatus.CONFLICTING_MATCHES, {case.status for case in cases})

    def test_explicit_multiple_targets_are_supported(self):
        items = (mapping("m1", allows_multiple_targets=True), mapping("m2", path=r"I:\Shows\Other", allows_multiple_targets=True))
        self.assertEqual(validate_mappings("1", items), ())

    def test_movie_to_tv_requires_manual_approval(self):
        auto = mapping(content_kind=TrackingContentKind.MOVIE, source=MappingSource.SCANNER)
        cases = validate_mappings("1", (auto,))
        self.assertIn(ReviewStatus.IDENTITY_CONFLICT, {case.status for case in cases})

    def test_mapping_history_is_preserved_by_inactive_record(self):
        old = mapping("old", active=False, superseded_at=NOW)
        current = mapping("new", season=2)
        self.assertEqual(len((old, current)), 2)
        self.assertNotIn("old", mapping_fingerprint((old, current)))

    def test_exact_path_rejection_does_not_reject_other_path(self):
        rejected = RejectedMatchDecision("r", "1", RejectionScope.EXACT_PATH, r"I:\Shows\Wrong", NOW)
        self.assertTrue(is_candidate_rejected((rejected,), path=r"i:\shows\wrong"))
        self.assertFalse(is_candidate_rejected((rejected,), path=r"I:\Shows\Right"))

    def test_candidate_and_library_rejections_persist(self):
        decisions = (
            RejectedMatchDecision("r1", "1", RejectionScope.CANDIDATE, "c1", NOW),
            RejectedMatchDecision("r2", "1", RejectionScope.LIBRARY_ITEM, "jf-2", NOW),
        )
        self.assertTrue(is_candidate_rejected(decisions, candidate_id="c1"))
        self.assertTrue(is_candidate_rejected(decisions, stable_item_id="jf-2"))

    def test_expired_rejection_no_longer_blocks(self):
        rejected = RejectedMatchDecision("r", "1", RejectionScope.EXACT_PATH, "x", NOW, expires_at=NOW)
        self.assertFalse(is_candidate_rejected((rejected,), path="x", at=NOW))

    def test_suppress_auto_match_override_persists(self):
        override = ManualOverride("o", "1", OverrideType.SUPPRESS_AUTOMATIC_MATCHING, True, NOW)
        self.assertTrue(suppresses_automatic_matching((override,), NOW))


class ReviewTests(unittest.TestCase):
    def test_no_match_creates_no_review(self):
        self.assertEqual(generate_review_cases(tracked_id="1"), ())

    def test_empty_candidates_create_no_review(self):
        self.assertEqual(generate_review_cases(tracked_id="1", candidates=()), ())

    def test_one_candidate_creates_no_review(self):
        candidate = MatchCandidateEvidence("c", "path", 90)
        self.assertEqual(generate_review_cases(tracked_id="1", candidates=(candidate,)), ())

    def test_equal_candidates_create_ambiguous_review(self):
        candidates = (MatchCandidateEvidence("a", "a", 90), MatchCandidateEvidence("b", "b", 90))
        cases = generate_review_cases(tracked_id="1", candidates=candidates)
        self.assertEqual(cases[0].status, ReviewStatus.AMBIGUOUS_MATCH)

    def test_missing_confirmed_path_creates_review(self):
        cases = generate_review_cases(tracked_id="1", confirmed_path_missing=True)
        self.assertEqual(cases[0].status, ReviewStatus.MISSING_CONFIRMED_PATH)

    def test_unresolved_ova_creates_special_review(self):
        cases = generate_review_cases(tracked_id="1", media_kind=MediaKind.OVA, special_mapping_resolved=False)
        self.assertEqual(cases[0].status, ReviewStatus.SPECIAL_MAPPING_REQUIRED)

    def test_multiple_possible_special_parents_create_ambiguity(self):
        parents = (MatchCandidateEvidence("parent-1", "p1", 80), MatchCandidateEvidence("parent-2", "p2", 80))
        cases = generate_review_cases(tracked_id="1", candidates=parents, media_kind=MediaKind.SPECIAL, special_mapping_resolved=False)
        self.assertEqual({case.status for case in cases}, {ReviewStatus.AMBIGUOUS_MATCH, ReviewStatus.SPECIAL_MAPPING_REQUIRED})

    def test_resolved_conflict_clears_review(self):
        conflicting = (mapping("m1"), mapping("m2", path=r"I:\Shows\Other"))
        self.assertTrue(generate_review_cases(tracked_id="1", mappings=conflicting))
        resolved = (mapping("m1"), replace(mapping("m2", path=r"I:\Shows\Other"), active=False))
        self.assertEqual(generate_review_cases(tracked_id="1", mappings=resolved), ())


class ArchiveTests(unittest.TestCase):
    def test_archive_preserves_all_related_data_and_restore_works(self):
        tracked = TrackedMedia("1", identity())
        map_record = mapping()
        rejection = RejectedMatchDecision("r", "1", RejectionScope.EXACT_PATH, "wrong", NOW)
        bundle = ArchiveBundle(tracked, (map_record,), (rejection,), (), ("notification-event",))
        archived = archive_tracked_media(bundle, NOW, "No longer tracking")
        self.assertTrue(archived.bundle.tracked_media.is_archived)
        self.assertEqual(archived.bundle.mappings, (map_record,))
        self.assertEqual(archived.bundle.rejections, (rejection,))
        self.assertEqual(archived.bundle.notification_history, ("notification-event",))
        restored = restore_tracked_media(archived)
        self.assertFalse(restored.tracked_media.is_archived)
        self.assertEqual(restored.mappings, bundle.mappings)

    def test_archived_title_is_removed_from_active_results(self):
        active = ArchiveBundle(TrackedMedia("1", identity()))
        archived = archive_tracked_media(ArchiveBundle(TrackedMedia("2", identity(anilist_id=2))), NOW).bundle
        self.assertEqual(active_only((active, archived)), (active,))


if __name__ == "__main__":
    unittest.main()
