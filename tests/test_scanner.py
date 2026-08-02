import json
import unittest

from anime_tracker.scanner import ServerCandidate, match_record, scan_roots


class Row(dict):
    def __getitem__(self, key):
        return dict.__getitem__(self, key)


def make_row(**kwargs):
    base = {
        "english_title": "Frieren: Beyond Journey's End",
        "romaji_title": "Sousou no Frieren",
        "native_title": "",
        "alternate_titles": json.dumps(["Frieren"]),
        "year": 2023,
        "format": "TV",
    }
    base.update(kwargs)
    return Row(base)


class ScannerTests(unittest.TestCase):
    def test_confident_match_requires_exact_normalized_title_and_kind(self):
        result = match_record(
            make_row(),
            [ServerCandidate(r"I:\Jellyfin_Media\TV-SHOWs\Frieren Beyond Journey's End (2023)", "frieren beyond journey s end", 2023, "TV")],
        )
        self.assertEqual(result.confidence, "confident")

    def test_movie_does_not_match_tv_folder(self):
        result = match_record(
            make_row(format="MOVIE"),
            [ServerCandidate(r"I:\Jellyfin_Media\TV-SHOWs\Frieren Beyond Journey's End (2023)", "frieren beyond journey s end", 2023, "TV")],
        )
        self.assertEqual(result.confidence, "none")

    def test_loose_match_is_uncertain_not_definitive(self):
        result = match_record(
            make_row(),
            [ServerCandidate(r"I:\Jellyfin_Media\TV-SHOWs\Frieren Journey End", "frieren journey end", 2023, "TV")],
        )
        self.assertEqual(result.confidence, "uncertain")

    def test_episode_filename_can_prove_season_presence(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tv = root / "tv"
            movies = root / "movies"
            show = tv / "Frieren Beyond Journey's End (2023)"
            show.mkdir(parents=True)
            movies.mkdir()
            (show / "Frieren.S02E01.mkv").touch()

            candidates = scan_roots(str(tv), str(movies))
            result = match_record(make_row(relation_label="Season 2"), candidates)

            self.assertEqual(result.confidence, "confident")
            self.assertIn(2, candidates[0].season_numbers)

    def test_nested_episode_path_can_prove_season_presence(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tv = root / "tv"
            movies = root / "movies"
            nested = tv / "Frieren Beyond Journey's End (2023)" / "Anime" / "Season 02" / "Video"
            nested.mkdir(parents=True)
            movies.mkdir()
            (nested / "Frieren.S02E01.mkv").touch()

            candidates = scan_roots(str(tv), str(movies))

            self.assertIn(2, candidates[0].season_numbers)
            self.assertEqual(match_record(make_row(relation_label="Season 2"), candidates).confidence, "confident")

    def test_unresolved_releasing_sequel_is_not_matched_or_sent_to_review(self):
        row = make_row(relation_label="Sequel", airing_status="RELEASING")
        result = match_record(
            row,
            [ServerCandidate(r"I:\TV\Frieren (2023)", "frieren", 2023, "TV", season_numbers=frozenset({1}))],
        )
        self.assertEqual(result.confidence, "none")
        self.assertEqual(result.candidates, [])


if __name__ == "__main__":
    unittest.main()
