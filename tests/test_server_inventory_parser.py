from __future__ import annotations

import unittest
from pathlib import Path

from anime_tracker.services.server_inventory.models import FileClassification, SpecialKind
from anime_tracker.services.server_inventory.parser import (
    classify_non_media,
    extract_year,
    parse_media_name,
    season_directory_number,
    special_directory_kind,
)


class ServerInventoryParserTests(unittest.TestCase):
    def parse(self, name, *, season=None, special=None, movie=False, parts=None):
        path = Path(name)
        return parse_media_name(
            path,
            relative_parts=parts or (name,),
            library_is_movie=movie,
            folder_season=season,
            special_kind=special,
        )

    def test_common_sxxexx_episode(self):
        parsed = self.parse("Example.Show.S02E03.1080p.mkv")
        self.assertEqual((parsed.season_number, parsed.episode_numbers), (2, (3,)))

    def test_common_x_episode(self):
        parsed = self.parse("Example Show - 2x04.mkv")
        self.assertEqual((parsed.season_number, parsed.episode_numbers), (2, (4,)))

    def test_multi_episode_dash_range(self):
        parsed = self.parse("Example.S01E03-E05.mkv")
        self.assertEqual(parsed.episode_numbers, (3, 4, 5))

    def test_multi_episode_joined_range(self):
        parsed = self.parse("Example.S01E03E04.mkv")
        self.assertEqual(parsed.episode_numbers, (3, 4))

    def test_implausible_multi_episode_range_is_unrecognized(self):
        parsed = self.parse("Example.S01E001-E999.mkv")
        self.assertEqual(parsed.classification, FileClassification.UNRECOGNIZED_MEDIA)

    def test_leading_number_requires_a_season_folder(self):
        parsed = self.parse("03 - A Title.mkv", season=2)
        self.assertEqual((parsed.season_number, parsed.episode_numbers), (2, (3,)))
        absolute = self.parse("03 - A Title.mkv")
        self.assertEqual(absolute.classification, FileClassification.UNRECOGNIZED_MEDIA)
        self.assertEqual(absolute.absolute_episode_numbers, (3,))

    def test_season_directories_with_and_without_leading_zero(self):
        self.assertEqual(season_directory_number("Season 02"), 2)
        self.assertEqual(season_directory_number("Season 2"), 2)
        self.assertEqual(season_directory_number("S02"), 2)

    def test_season_zero_and_specials(self):
        self.assertEqual(season_directory_number("Season 00"), 0)
        self.assertEqual(special_directory_kind("Specials"), SpecialKind.SPECIAL)

    def test_ova_and_ona_directories_are_explicit_special_groups(self):
        self.assertEqual(special_directory_kind("OVA"), SpecialKind.OVA)
        self.assertEqual(special_directory_kind("ONAs"), SpecialKind.ONA)

    def test_numberless_media_in_explicit_ova_folder_stays_special(self):
        parsed = self.parse("bonus-feature.mkv", season=0, special=SpecialKind.OVA)
        self.assertEqual(parsed.classification, FileClassification.SPECIAL)
        self.assertEqual(parsed.episode_numbers, ())

    def test_special_episode_from_filename(self):
        parsed = self.parse("Example.S00E02.mkv")
        self.assertEqual((parsed.classification, parsed.season_number), (FileClassification.SPECIAL, 0))

    def test_movie_root_media_is_movie_without_title_inference(self):
        parsed = self.parse("Movie.Title.2025.v2.mkv", movie=True)
        self.assertEqual(parsed.classification, FileClassification.MOVIE)

    def test_version_suffix_is_not_interpreted(self):
        parsed = self.parse("Example.S01E02v3.mkv")
        self.assertEqual(parsed.episode_numbers, (2,))

    def test_artwork_subtitle_and_metadata_classification(self):
        self.assertEqual(classify_non_media(Path("poster.jpg"), ("poster.jpg",)), FileClassification.ARTWORK)
        self.assertEqual(classify_non_media(Path("episode.ass"), ("episode.ass",)), FileClassification.SUBTITLE)
        self.assertEqual(classify_non_media(Path("movie.nfo"), ("movie.nfo",)), FileClassification.METADATA)

    def test_sample_and_extra_directories_are_not_media(self):
        parsed = self.parse("sample.mkv", parts=("Samples", "sample.mkv"))
        self.assertEqual(parsed.classification, FileClassification.EXTRA)

    def test_year_uses_a_standalone_four_digit_value(self):
        self.assertEqual(extract_year("Frieren (2023)"), 2023)
        self.assertIsNone(extract_year("Episode.20231"))


if __name__ == "__main__":
    unittest.main()
