from __future__ import annotations

import unittest

from anime_tracker.domain.coverage import calculate_episode_coverage, determine_server_presence
from anime_tracker.domain.enums import AniListStatus, CoverageSource, MediaKind, ServerPresence

from domain_helpers import identity


class EpisodeCoverageTests(unittest.TestCase):
    def coverage(self, expected=12, aired=4, present=()):
        return calculate_episode_coverage(
            expected_total_episodes=expected,
            aired_episode_count=aired,
            present_episode_numbers=present,
            coverage_source=CoverageSource.FILESYSTEM,
        )

    def presence(self, status, present, expected=12, aired=4):
        media = identity(status=status, expected=expected)
        coverage = self.coverage(expected, aired, present)
        return determine_server_presence(media, mapping_confirmed=True, path_exists=True, coverage=coverage)

    def test_no_mapping_is_normal_not_found(self):
        state = determine_server_presence(identity(), mapping_confirmed=False)
        self.assertEqual(state.presence, ServerPresence.NOT_FOUND)

    def test_confirmed_missing_path(self):
        state = determine_server_presence(identity(), mapping_confirmed=True, path_exists=False)
        self.assertEqual(state.presence, ServerPresence.PATH_MISSING)

    def test_confirmed_mapping_without_inventory_is_unknown(self):
        state = determine_server_presence(identity(), mapping_confirmed=True, path_exists=True)
        self.assertEqual(state.presence, ServerPresence.UNKNOWN_COVERAGE)

    def test_airing_no_episodes_present(self):
        self.assertEqual(self.presence(AniListStatus.RELEASING, ()).presence, ServerPresence.NOT_FOUND)

    def test_airing_some_aired_episodes_present(self):
        self.assertEqual(self.presence(AniListStatus.RELEASING, (1, 2)).presence, ServerPresence.PARTIAL)

    def test_airing_all_aired_episodes_present(self):
        self.assertEqual(self.presence(AniListStatus.RELEASING, (1, 2, 3, 4)).presence, ServerPresence.COMPLETE)

    def test_airing_future_episodes_are_not_required(self):
        state = self.presence(AniListStatus.RELEASING, (1, 2, 3, 4), expected=12, aired=4)
        self.assertEqual(state.presence, ServerPresence.COMPLETE)
        self.assertEqual(state.coverage.missing_expected_episode_numbers, frozenset(range(5, 13)))

    def test_airing_unknown_aired_count_is_unknown_coverage(self):
        self.assertEqual(self.presence(AniListStatus.RELEASING, (1, 2), aired=None).presence, ServerPresence.UNKNOWN_COVERAGE)

    def test_duplicate_episode_numbers_are_recorded(self):
        coverage = self.coverage(present=(1, 1, 2))
        self.assertEqual(coverage.duplicate_episode_numbers, frozenset({1}))
        self.assertTrue(coverage.warnings)

    def test_generator_input_is_consumed_once_safely(self):
        coverage = self.coverage(present=(item for item in (1, None, 2)))
        self.assertEqual(coverage.present_episode_numbers, frozenset({1, 2}))
        self.assertEqual(coverage.unknown_numbered_files, 1)

    def test_finished_all_expected_present(self):
        self.assertEqual(self.presence(AniListStatus.FINISHED, range(1, 13)).presence, ServerPresence.COMPLETE)

    def test_finished_partial(self):
        self.assertEqual(self.presence(AniListStatus.FINISHED, range(1, 11)).presence, ServerPresence.PARTIAL)

    def test_finished_none(self):
        self.assertEqual(self.presence(AniListStatus.FINISHED, ()).presence, ServerPresence.NOT_FOUND)

    def test_finished_unknown_expected_count(self):
        self.assertEqual(self.presence(AniListStatus.FINISHED, (1, 2), expected=None).presence, ServerPresence.UNKNOWN_COVERAGE)

    def test_finished_extra_episode_does_not_prevent_complete(self):
        state = self.presence(AniListStatus.FINISHED, range(1, 14))
        self.assertEqual(state.presence, ServerPresence.COMPLETE)
        self.assertIn("Episode numbers above", " ".join(state.warnings))

    def test_movie_requires_confirmed_movie_item(self):
        movie = identity(kind=MediaKind.MOVIE)
        absent = determine_server_presence(movie, mapping_confirmed=True, movie_item_present=False)
        present = determine_server_presence(movie, mapping_confirmed=True, movie_item_present=True)
        self.assertEqual((absent.presence, present.presence), (ServerPresence.NOT_FOUND, ServerPresence.COMPLETE))

    def test_similarly_named_series_does_not_satisfy_movie(self):
        movie = identity(kind=MediaKind.MOVIE)
        state = determine_server_presence(movie, mapping_confirmed=False, movie_item_present=True)
        self.assertEqual(state.presence, ServerPresence.NOT_FOUND)

    def test_unresolved_special_has_unknown_coverage(self):
        special = identity(kind=MediaKind.OVA)
        state = determine_server_presence(special, mapping_confirmed=True, path_exists=True, special_mapping_resolved=False)
        self.assertEqual(state.presence, ServerPresence.UNKNOWN_COVERAGE)


if __name__ == "__main__":
    unittest.main()
