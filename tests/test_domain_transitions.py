from __future__ import annotations

import unittest
from dataclasses import replace

from anime_tracker.domain.enums import (
    AniListStatus,
    ReviewStatus,
    ServerPresence,
    TrackerWorkflowStatus,
    TransitionEventType,
)
from anime_tracker.domain.models import StatusDecision
from anime_tracker.domain.transitions import compare_status_decisions


def decision(
    workflow=TrackerWorkflowStatus.UPCOMING,
    anilist=AniListStatus.NOT_YET_RELEASED,
    presence=ServerPresence.NOT_FOUND,
    review=ReviewStatus.NONE,
    aired=None,
    mapping="",
):
    return StatusDecision(workflow, anilist, presence, review, "TEST", aired_episode_count=aired, mapping_fingerprint=mapping)


def types(previous, current):
    return {event.event_type for event in compare_status_decisions(1, previous, current)}


class TransitionTests(unittest.TestCase):
    def test_tracking_started(self):
        self.assertEqual(types(None, decision()), {TransitionEventType.TRACKING_STARTED})

    def test_upcoming_to_airing(self):
        current = decision(TrackerWorkflowStatus.CURRENTLY_AIRING, AniListStatus.RELEASING)
        self.assertIn(TransitionEventType.STARTED_AIRING, types(decision(), current))

    def test_airing_to_finished(self):
        previous = decision(TrackerWorkflowStatus.CURRENTLY_AIRING, AniListStatus.RELEASING)
        current = decision(TrackerWorkflowStatus.FINISHED_READY_TO_ADD, AniListStatus.FINISHED)
        self.assertIn(TransitionEventType.SERIES_FINISHED, types(previous, current))

    def test_new_episode_aired(self):
        previous = decision(TrackerWorkflowStatus.CURRENTLY_AIRING, AniListStatus.RELEASING, aired=4)
        current = replace(previous, aired_episode_count=5)
        self.assertEqual(types(previous, current), {TransitionEventType.NEW_EPISODE_AIRED})

    def test_partial_to_complete(self):
        previous = decision(TrackerWorkflowStatus.CURRENTLY_AIRING, AniListStatus.RELEASING, ServerPresence.PARTIAL)
        current = decision(TrackerWorkflowStatus.ON_SERVER, AniListStatus.RELEASING, ServerPresence.COMPLETE)
        self.assertIn(TransitionEventType.COVERAGE_BECAME_COMPLETE, types(previous, current))

    def test_complete_to_partial_is_coverage_lost(self):
        previous = decision(TrackerWorkflowStatus.ON_SERVER, AniListStatus.RELEASING, ServerPresence.COMPLETE)
        current = decision(TrackerWorkflowStatus.CURRENTLY_AIRING, AniListStatus.RELEASING, ServerPresence.PARTIAL)
        self.assertIn(TransitionEventType.COVERAGE_LOST, types(previous, current))

    def test_not_found_to_found(self):
        previous = decision(presence=ServerPresence.NOT_FOUND)
        current = decision(TrackerWorkflowStatus.ON_SERVER, AniListStatus.NOT_YET_RELEASED, ServerPresence.COMPLETE)
        self.assertIn(TransitionEventType.FOUND_ON_SERVER, types(previous, current))

    def test_no_longer_found(self):
        previous = decision(TrackerWorkflowStatus.ON_SERVER, AniListStatus.FINISHED, ServerPresence.COMPLETE)
        current = decision(TrackerWorkflowStatus.FINISHED_READY_TO_ADD, AniListStatus.FINISHED, ServerPresence.NOT_FOUND)
        self.assertIn(TransitionEventType.NO_LONGER_FOUND_ON_SERVER, types(previous, current))

    def test_mapping_changed(self):
        previous = decision(mapping="old")
        current = decision(mapping="new")
        self.assertEqual(types(previous, current), {TransitionEventType.MAPPING_CHANGED})

    def test_review_opened(self):
        previous = decision()
        current = decision(TrackerWorkflowStatus.NEEDS_REVIEW, review=ReviewStatus.IDENTITY_CONFLICT)
        self.assertIn(TransitionEventType.REVIEW_REQUIRED, types(previous, current))

    def test_review_resolved(self):
        previous = decision(TrackerWorkflowStatus.NEEDS_REVIEW, review=ReviewStatus.IDENTITY_CONFLICT)
        current = decision()
        self.assertIn(TransitionEventType.REVIEW_RESOLVED, types(previous, current))

    def test_archived_and_restored(self):
        archived = decision(TrackerWorkflowStatus.ARCHIVED)
        self.assertIn(TransitionEventType.ARCHIVED, types(decision(), archived))
        self.assertIn(TransitionEventType.RESTORED, types(archived, decision()))

    def test_movie_transitions(self):
        theatrical = decision(TrackerWorkflowStatus.MOVIE_THEATRICAL_ONLY, AniListStatus.FINISHED)
        digital = decision(TrackerWorkflowStatus.MOVIE_DIGITALLY_AVAILABLE, AniListStatus.FINISHED)
        self.assertIn(TransitionEventType.MOVIE_BECAME_THEATRICAL, types(decision(), theatrical))
        self.assertIn(TransitionEventType.MOVIE_BECAME_DIGITAL, types(theatrical, digital))

    def test_unchanged_state_has_no_duplicate_event(self):
        current = decision(TrackerWorkflowStatus.CURRENTLY_AIRING, AniListStatus.RELEASING, ServerPresence.PARTIAL, aired=5, mapping="x")
        self.assertEqual(compare_status_decisions(1, current, current), ())


if __name__ == "__main__":
    unittest.main()
