from __future__ import annotations

import unittest
from dataclasses import replace

from anime_tracker.domain.coverage import calculate_episode_coverage, determine_server_presence
from anime_tracker.domain.enums import (
    AniListStatus,
    MediaKind,
    OverrideSource,
    OverrideType,
    ReviewStatus,
    ServerPresence,
    TrackerWorkflowStatus,
)
from anime_tracker.domain.models import ManualOverride, ReviewCase, StatusDecisionInput
from anime_tracker.domain.status_engine import decide_status

from domain_helpers import NOW, decision_input, identity


class StatusEngineTests(unittest.TestCase):
    def test_anilist_status_is_independent_from_on_server_workflow(self):
        result = decide_status(decision_input(media=identity(status=AniListStatus.RELEASING), presence=ServerPresence.COMPLETE))
        self.assertEqual(result.anilist_status, AniListStatus.RELEASING)
        self.assertEqual(result.workflow_status, TrackerWorkflowStatus.ON_SERVER)

    def test_tracker_status_is_independent_from_partial_presence(self):
        result = decide_status(decision_input(media=identity(status=AniListStatus.RELEASING), presence=ServerPresence.PARTIAL))
        self.assertEqual(result.workflow_status, TrackerWorkflowStatus.CURRENTLY_AIRING)
        self.assertEqual(result.server_presence, ServerPresence.PARTIAL)

    def test_no_match_has_no_review(self):
        result = decide_status(decision_input(media=identity(status=AniListStatus.FINISHED)))
        self.assertEqual(result.workflow_status, TrackerWorkflowStatus.FINISHED_READY_TO_ADD)
        self.assertEqual(result.review_status, ReviewStatus.NONE)

    def test_blocking_review_precedes_complete_server(self):
        case = ReviewCase("r", "1", ReviewStatus.IDENTITY_CONFLICT, "IDENTITY", "Identity conflict")
        result = decide_status(decision_input(presence=ServerPresence.COMPLETE, review_cases=(case,)))
        self.assertEqual(result.workflow_status, TrackerWorkflowStatus.NEEDS_REVIEW)

    def test_nonblocking_review_remains_independent(self):
        case = ReviewCase("r", "1", ReviewStatus.MANUAL_REVIEW, "NOTE", "Check later", blocking=False)
        result = decide_status(decision_input(media=identity(status=AniListStatus.RELEASING), review_cases=(case,)))
        self.assertEqual(result.workflow_status, TrackerWorkflowStatus.CURRENTLY_AIRING)
        self.assertEqual(result.review_status, ReviewStatus.MANUAL_REVIEW)

    def test_archived_has_highest_default_precedence(self):
        result = decide_status(decision_input(presence=ServerPresence.COMPLETE, archived=True))
        self.assertEqual(result.workflow_status, TrackerWorkflowStatus.ARCHIVED)

    def test_upcoming(self):
        result = decide_status(decision_input(media=identity(status=AniListStatus.NOT_YET_RELEASED)))
        self.assertEqual(result.workflow_status, TrackerWorkflowStatus.UPCOMING)

    def test_releasing(self):
        result = decide_status(decision_input(media=identity(status=AniListStatus.RELEASING)))
        self.assertEqual(result.workflow_status, TrackerWorkflowStatus.CURRENTLY_AIRING)

    def test_hiatus_is_kept_in_airing_workflow(self):
        result = decide_status(decision_input(media=identity(status=AniListStatus.HIATUS)))
        self.assertEqual(result.workflow_status, TrackerWorkflowStatus.CURRENTLY_AIRING)

    def test_finished_partial_is_ready(self):
        result = decide_status(decision_input(presence=ServerPresence.PARTIAL))
        self.assertEqual(result.workflow_status, TrackerWorkflowStatus.FINISHED_READY_TO_ADD)

    def test_movie_not_released_is_upcoming(self):
        result = decide_status(decision_input(media=identity(status=AniListStatus.NOT_YET_RELEASED, kind=MediaKind.MOVIE)))
        self.assertEqual(result.workflow_status, TrackerWorkflowStatus.UPCOMING)

    def test_movie_theatrical_only(self):
        result = decide_status(decision_input(media=identity(kind=MediaKind.MOVIE), movie_theatrical_released=True))
        self.assertEqual(result.workflow_status, TrackerWorkflowStatus.MOVIE_THEATRICAL_ONLY)

    def test_movie_digitally_available(self):
        result = decide_status(decision_input(media=identity(kind=MediaKind.MOVIE), movie_theatrical_released=True, movie_digital_available=True))
        self.assertEqual(result.workflow_status, TrackerWorkflowStatus.MOVIE_DIGITALLY_AVAILABLE)

    def test_movie_on_server_precedes_availability(self):
        result = decide_status(decision_input(media=identity(kind=MediaKind.MOVIE), presence=ServerPresence.COMPLETE, movie_digital_available=True))
        self.assertEqual(result.workflow_status, TrackerWorkflowStatus.ON_SERVER)

    def test_unknown_status_has_deterministic_warning_fallback(self):
        result = decide_status(decision_input(media=identity(status=AniListStatus.UNKNOWN)))
        self.assertEqual(result.workflow_status, TrackerWorkflowStatus.UPCOMING)
        self.assertTrue(result.warnings)

    def test_structured_airing_coverage_reasons(self):
        media = identity(status=AniListStatus.RELEASING)
        coverage = calculate_episode_coverage(expected_total_episodes=12, aired_episode_count=5, present_episode_numbers=(1, 2, 3))
        server = determine_server_presence(media, mapping_confirmed=True, path_exists=True, coverage=coverage)
        result = decide_status(StatusDecisionInput(media, server))
        reason = next(item for item in result.reasons if item.code == "AIRED_COVERAGE")
        self.assertIn(("missing", "4,5"), reason.details)

    def test_force_workflow_override_is_visible(self):
        override = ManualOverride("o1", "1", OverrideType.FORCE_WORKFLOW_STATUS, TrackerWorkflowStatus.ON_SERVER, NOW, source=OverrideSource.USER)
        result = decide_status(decision_input(overrides=(override,), decided_at=NOW))
        self.assertEqual(result.workflow_status, TrackerWorkflowStatus.ON_SERVER)
        self.assertTrue(result.override_changed_outcome)
        self.assertEqual(result.applied_override_ids, ("o1",))

    def test_force_presence_override_is_visible(self):
        override = ManualOverride("o1", "1", OverrideType.FORCE_SERVER_PRESENCE, ServerPresence.COMPLETE, NOW)
        result = decide_status(decision_input(overrides=(override,), decided_at=NOW))
        self.assertEqual(result.server_presence, ServerPresence.COMPLETE)
        self.assertEqual(result.workflow_status, TrackerWorkflowStatus.ON_SERVER)

    def test_clearing_override_restores_computed_status(self):
        override = ManualOverride("o1", "1", OverrideType.FORCE_WORKFLOW_STATUS, TrackerWorkflowStatus.ON_SERVER, NOW, active=False)
        result = decide_status(decision_input(overrides=(override,), decided_at=NOW))
        self.assertEqual(result.workflow_status, TrackerWorkflowStatus.FINISHED_READY_TO_ADD)
        self.assertFalse(result.override_changed_outcome)

    def test_override_does_not_mutate_provider_evidence(self):
        media = identity(status=AniListStatus.FINISHED)
        override = ManualOverride("o1", "1", OverrideType.FORCE_WORKFLOW_STATUS, TrackerWorkflowStatus.UPCOMING, NOW)
        result = decide_status(decision_input(media=media, overrides=(override,), decided_at=NOW))
        self.assertEqual(media.status, AniListStatus.FINISHED)
        self.assertEqual(result.anilist_status, AniListStatus.FINISHED)

    def test_expiration_requires_explicit_decision_time(self):
        override = ManualOverride("o1", "1", OverrideType.FORCE_WORKFLOW_STATUS, TrackerWorkflowStatus.ON_SERVER, NOW, expires_at=NOW)
        without_clock = decide_status(decision_input(overrides=(override,)))
        at_expiration = decide_status(decision_input(overrides=(override,), decided_at=NOW))
        self.assertEqual(without_clock.workflow_status, TrackerWorkflowStatus.ON_SERVER)
        self.assertEqual(at_expiration.workflow_status, TrackerWorkflowStatus.FINISHED_READY_TO_ADD)


if __name__ == "__main__":
    unittest.main()
