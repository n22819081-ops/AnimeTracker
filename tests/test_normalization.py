import unittest

from anime_tracker.normalization import normalize_title


class NormalizationTests(unittest.TestCase):
    def test_normalize_title_removes_noise_and_punctuation(self):
        self.assertEqual(normalize_title("Frieren: Beyond Journey's End (TV)"), "frieren beyond journey s end")

    def test_normalize_title_handles_accents_and_season_text(self):
        self.assertEqual(normalize_title("Pokémon Season 2"), "pokemon")


if __name__ == "__main__":
    unittest.main()
