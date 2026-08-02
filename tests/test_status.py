import unittest

from anime_tracker.constants import (
    TRACKER_AIRING,
    TRACKER_MOVIE_DIGITAL,
    TRACKER_MOVIE_THEATRICAL,
    TRACKER_READY,
    TRACKER_UPCOMING,
)
from anime_tracker.status import is_meaningful_transition, tracker_status_from_anilist


class StatusTests(unittest.TestCase):
    def test_status_transitions_for_series(self):
        self.assertEqual(tracker_status_from_anilist("NOT_YET_RELEASED", "TV"), TRACKER_UPCOMING)
        self.assertEqual(tracker_status_from_anilist("RELEASING", "TV"), TRACKER_AIRING)
        self.assertEqual(tracker_status_from_anilist("FINISHED", "TV"), TRACKER_READY)


    def test_movie_requires_manual_digital_availability(self):
        self.assertEqual(tracker_status_from_anilist("FINISHED", "MOVIE"), TRACKER_MOVIE_THEATRICAL)
        self.assertEqual(tracker_status_from_anilist("FINISHED", "MOVIE", "digital"), TRACKER_MOVIE_DIGITAL)


    def test_meaningful_notifications_are_limited(self):
        self.assertTrue(is_meaningful_transition(TRACKER_UPCOMING, TRACKER_AIRING))
        self.assertTrue(is_meaningful_transition(TRACKER_AIRING, TRACKER_READY))
        self.assertFalse(is_meaningful_transition(TRACKER_READY, TRACKER_READY))


if __name__ == "__main__":
    unittest.main()
