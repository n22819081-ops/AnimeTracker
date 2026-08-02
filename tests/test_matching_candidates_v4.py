from __future__ import annotations

import unittest
from dataclasses import replace

from anime_tracker.domain.enums import LibraryKind, MediaKind
from anime_tracker.services.matching.candidates import generate_match_candidates, inventory_snapshot_id, media_version
from anime_tracker.services.matching.models import (
    ConfirmationState,
    MappingSource,
    MappingTarget,
    MappingTargetType,
    MatchConfidence,
    MatchingRejection,
    MatchingRejectionScope,
    MatchingSession,
    PathState,
    PersistentMapping,
)
from anime_tracker.services.server_inventory.models import SpecialKind
from anime_tracker.domain.enums import TrackingContentKind

from matching_helpers import NOW, episode_file, inventory_item, media, relation, snapshot


def session(media_value, inventory, key="session-1"):
    return MatchingSession(key, "default", inventory_snapshot_id(inventory), media_version(media_value), NOW, NOW)


def generate(media_value, inventory, **kwargs):
    return generate_match_candidates(media_value, inventory, session(media_value, inventory), **kwargs)


class CandidateIdentityTests(unittest.TestCase):
    def test_exact_english_title(self):
        result = generate(media("Example Anime"), snapshot(inventory_item()))
        self.assertTrue(result.candidates[0].evidence.exact_title_variant)

    def test_exact_romaji_title(self):
        value = media("Primary", english="", romaji="Sousou no Example")
        result = generate(value, snapshot(inventory_item("Sousou no Example (2024)")))
        self.assertEqual(result.candidates[0].evidence.matched_title, "Sousou no Example")

    def test_exact_native_title(self):
        value = media("Primary", english="", native="例のアニメ")
        result = generate(value, snapshot(inventory_item("例のアニメ (2024)")))
        self.assertEqual(result.candidates[0].evidence.matched_title, "例のアニメ")

    def test_exact_synonym(self):
        value = media("Primary", synonyms=("Alternative Example",))
        result = generate(value, snapshot(inventory_item("Alternative Example (2024)")))
        self.assertEqual(result.candidates[0].evidence.matched_title, "Alternative Example")

    def test_year_agreement_adds_evidence(self):
        result = generate(media(year=2024), snapshot(inventory_item(year=2024)))
        self.assertTrue(result.candidates[0].evidence.year_agreement)

    def test_year_conflict_is_visible(self):
        result = generate(media(year=2026), snapshot(inventory_item(year=2024)))
        self.assertTrue(result.candidates[0].evidence.year_conflict)
        self.assertIn("folder year conflict", dict(result.candidates[0].evidence.score_components))

    def test_similar_unrelated_title_does_not_qualify_on_season_alone(self):
        value = media("Completely Different Season 2", year=2026)
        result = generate(value, snapshot(inventory_item("Example Anime (2024)", seasons={2: range(1, 13)})))
        self.assertEqual(result.candidates, ())

    def test_no_inventory_is_normal_zero_candidates(self):
        self.assertEqual(generate(media(), snapshot()).candidates, ())

    def test_candidate_ids_are_stable_within_session_and_independent_of_item_order(self):
        value = media()
        one = inventory_item(item_id="a")
        two = inventory_item("Example Anime Alternate (2024)", item_id="b")
        first_inventory = snapshot(one, two)
        second_inventory = snapshot(one, two, reverse=True)
        first = generate_match_candidates(value, first_inventory, session(value, first_inventory, "stable"))
        second = generate_match_candidates(value, second_inventory, session(value, second_inventory, "stable"))
        self.assertEqual([item.candidate_id for item in first.candidates], [item.candidate_id for item in second.candidates])


class SeasonScopeTests(unittest.TestCase):
    def test_season_one_does_not_satisfy_season_two(self):
        value = media("Example Anime Season 2", year=2026)
        result = generate(value, snapshot(inventory_item(seasons={1: range(1, 13)})))
        self.assertEqual(result.candidates, ())

    def test_season_two_uses_only_season_two_target(self):
        value = media("Example Anime Season 2", year=2026)
        result = generate(value, snapshot(inventory_item(seasons={1: range(1, 13), 2: range(1, 4)})))
        self.assertEqual({item.target.season_number for item in result.candidates}, {2})

    def test_folder_year_conflict_does_not_outweigh_explicit_season(self):
        value = media("Example Anime Season 2", year=2026)
        candidate = generate(value, snapshot(inventory_item(year=2024, seasons={2: range(1, 13)}))).candidates[0]
        self.assertTrue(candidate.evidence.season_evidence)
        self.assertTrue(candidate.evidence.year_conflict)
        self.assertIn(candidate.confidence, {MatchConfidence.STRONG, MatchConfidence.VERY_STRONG})

    def test_unknown_season_with_multiple_seasons_is_ambiguous_not_preselected(self):
        result = generate(media(), snapshot(inventory_item(seasons={1: range(1, 13), 2: range(1, 13)})))
        self.assertEqual({item.target.season_number for item in result.candidates}, {1, 2})
        self.assertFalse(any(item.preselected for item in result.candidates))

    def test_episode_range_evidence_is_season_scoped(self):
        value = media("Example Anime Season 2", episodes=12)
        candidate = generate(value, snapshot(inventory_item(seasons={2: range(1, 7)}))).candidates[0]
        self.assertEqual(candidate.evidence.episode_range, (1, 6))

    def test_mixed_folder_warning_blocks_preselection(self):
        unrecognized = (
            episode_file("mixed", 1, 13, absolute=True, name="13 - Other Show.mkv"),
            episode_file("mixed", 1, 14, absolute=True, name="14 - Another Show.mkv"),
        )
        candidate = generate(
            media(), snapshot(inventory_item(unrecognized=unrecognized)),
        ).candidates[0]
        self.assertTrue(candidate.evidence.mixed_folder_warning)
        self.assertFalse(candidate.preselected)


class MovieAndSpecialCandidateTests(unittest.TestCase):
    def test_exact_movie_match_uses_movies_inventory(self):
        value = media("Example Anime The Movie", kind=MediaKind.MOVIE)
        movie_item = inventory_item("Example Anime The Movie (2024)", item_id="movie", movie=True, kind=LibraryKind.MOVIE, root="Movies")
        candidate = generate(value, snapshot(movie_item)).candidates[0]
        self.assertEqual(candidate.target.target_type, MappingTargetType.MOVIE_ITEM)
        self.assertTrue(candidate.evidence.movie_evidence)

    def test_movie_does_not_match_related_tv_folder(self):
        value = media("Example Anime The Movie", kind=MediaKind.MOVIE)
        tv = inventory_item("Example Anime The Movie (2024)")
        self.assertEqual(generate(value, snapshot(tv)).candidates, ())

    def test_movie_without_year_can_still_be_strong(self):
        value = media("Example Anime The Movie", kind=MediaKind.MOVIE)
        item = inventory_item("Example Anime The Movie", year=None, movie=True, kind=LibraryKind.MOVIE, root="Movies")
        self.assertIn(generate(value, snapshot(item)).candidates[0].confidence, {MatchConfidence.STRONG, MatchConfidence.VERY_STRONG})

    def test_movie_alternate_title_matches(self):
        value = media("Primary Movie", synonyms=("Alternate Movie",), kind=MediaKind.MOVIE)
        item = inventory_item("Alternate Movie", year=None, movie=True, kind=LibraryKind.MOVIE, root="Movies")
        self.assertEqual(generate(value, snapshot(item)).candidates[0].evidence.matched_title, "Alternate Movie")

    def test_split_movie_files_remain_one_movie_candidate(self):
        value = media("Example Anime The Movie", kind=MediaKind.MOVIE)
        item = inventory_item("Example Anime The Movie", year=None, movie=True, kind=LibraryKind.MOVIE, root="Movies")
        second_part = replace(
            item.movie_files[0],
            relative_path="Part 2.mkv",
            normalized_path=item.movie_files[0].normalized_path.replace("example anime the movie.mkv", "part 2.mkv"),
        )
        split = replace(item, movie_files=(*item.movie_files, second_part))
        result = generate(value, snapshot(split))
        self.assertEqual(len(result.candidates), 1)
        self.assertEqual(result.candidates[0].target.target_type, MappingTargetType.MOVIE_ITEM)

    def test_recap_and_compilation_identity_remains_visible(self):
        recap = media("Example Anime Recap Movie", kind=MediaKind.MOVIE)
        item = inventory_item("Example Anime Recap Movie", year=None, movie=True, kind=LibraryKind.MOVIE, root="Movies")
        warnings = generate(recap, snapshot(item)).candidates[0].evidence.warnings
        self.assertTrue(any("recap" in warning.casefold() for warning in warnings))

    def test_ova_season_zero_is_suggestion_not_preselected(self):
        value = media("Example Anime OVA", kind=MediaKind.OVA, episodes=1)
        item = inventory_item(specials=((SpecialKind.OVA, (1,)),))
        candidate = generate(value, snapshot(item)).candidates[0]
        self.assertEqual((candidate.target.target_type, candidate.target.season_number), (MappingTargetType.SERIES_SPECIALS, 0))
        self.assertFalse(candidate.preselected)

    def test_separate_ona_series_is_supported(self):
        value = media("Example Anime ONA", kind=MediaKind.ONA)
        item = inventory_item("Example Anime ONA (2024)", item_id="ona", seasons={1: (1, 2)})
        targets = {candidate.target.target_type for candidate in generate(value, snapshot(item)).candidates}
        self.assertIn(MappingTargetType.SEPARATE_SERIES, targets)

    def test_ova_can_offer_movies_library_candidate_without_forcing_it(self):
        value = media("Example Anime OVA", kind=MediaKind.OVA, episodes=1)
        item = inventory_item("Example Anime OVA", year=None, movie=True, kind=LibraryKind.MOVIE, root="Movies")
        candidate = generate(value, snapshot(item)).candidates[0]
        self.assertEqual(candidate.target.target_type, MappingTargetType.MOVIE_ITEM)
        self.assertFalse(candidate.preselected)


class CandidateRejectionTests(unittest.TestCase):
    def target(self):
        return MappingTarget(
            MappingTargetType.SERIES_SEASON, LibraryKind.TV, "TV", "Example", "x:\\example",
            "item-example", 1, TrackingContentKind.SEASON, "snapshot", "Example", PathState.EXISTS,
        )

    def test_exact_target_rejection_marks_only_same_season_rejected(self):
        value = media()
        inventory = snapshot(inventory_item(seasons={1: (1,), 2: (1,)}))
        first = generate(value, inventory)
        season_one = next(item for item in first.candidates if item.target.season_number == 1)
        rejection = MatchingRejection(
            "r", "default", value.anilist_id, MatchingRejectionScope.EXACT_TARGET,
            season_one.target.identity_key, "wrong season", NOW,
        )
        second = generate(value, inventory, rejections=(rejection,))
        by_season = {item.target.season_number: item.confidence for item in second.candidates}
        self.assertEqual(by_season[1], MatchConfidence.REJECTED)
        self.assertNotEqual(by_season[2], MatchConfidence.REJECTED)

    def test_folder_rejection_applies_across_seasons(self):
        value = media()
        inventory = snapshot(inventory_item(seasons={1: (1,), 2: (1,)}))
        first = generate(value, inventory)
        rejection = MatchingRejection(
            "r", "default", value.anilist_id, MatchingRejectionScope.FOLDER,
            first.candidates[0].target.folder_identity_key, "wrong folder", NOW,
        )
        second = generate(value, inventory, rejections=(rejection,))
        self.assertTrue(all(item.confidence == MatchConfidence.REJECTED for item in second.candidates))

    def test_confirmed_mapping_wins_over_candidate_score(self):
        value = media()
        inventory = snapshot(inventory_item())
        target = generate(value, inventory).candidates[0].target
        mapping = PersistentMapping(
            "m", "default", value.anilist_id, target, MappingSource.MANUAL_CONFIRMATION,
            ConfirmationState.CONFIRMED, MatchConfidence.STRONG, NOW, NOW,
        )
        candidate = generate(value, inventory, mappings=(mapping,)).candidates[0]
        self.assertTrue(candidate.evidence.existing_confirmed_mapping)
        self.assertGreater(candidate.score, 1000)
        self.assertFalse(candidate.preselected)

    def test_relation_evidence_supports_parent_folder_but_not_missing_season(self):
        sequel = media("Example Anime Season 2", anilist_id=200, year=2026)
        inventory = snapshot(inventory_item(seasons={1: (1,), 2: (1,)}))
        parent_target = generate(media(), inventory).candidates[0].target
        parent = PersistentMapping(
            "parent", "default", 100, parent_target, MappingSource.MANUAL_CONFIRMATION,
            ConfirmationState.CONFIRMED, MatchConfidence.STRONG, NOW, NOW,
        )
        result = generate(sequel, inventory, mappings=(parent,), relations=(relation(200, 100),))
        self.assertEqual({item.target.season_number for item in result.candidates}, {2})
        self.assertTrue(result.candidates[0].evidence.franchise_relation_evidence)


if __name__ == "__main__":
    unittest.main()
