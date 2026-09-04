import json
import unittest

from anime_tracker.normalization import normalize_title
from anime_tracker.scanner import (
    ServerCandidate,
    candidate_supports_season,
    infer_tracked_seasons,
    match_record,
    multi_season_ids,
    tracked_season_number,
)


class Row(dict):
    pass


def make_row(anilist_id, english, romaji="", relation="", year=2023, format="TV", **kw):
    base = {
        "anilist_id": anilist_id,
        "english_title": english,
        "romaji_title": romaji,
        "native_title": "",
        "alternate_titles": json.dumps([]),
        "year": year,
        "format": format,
        "relation_label": relation,
        "airing_status": "RELEASING",
    }
    base.update(kw)
    return Row(base)


def cand(name, seasons, year=2023, kind="TV"):
    return ServerCandidate(
        path=f"I:\\Jellyfin_Media\\TV-SHOWs\\{name}",
        normalized_name=normalize_title(name),
        year=year,
        media_kind=kind,
        display_name=name,
        season_numbers=frozenset(seasons),
    )


class SeasonMatchingFixTests(unittest.TestCase):
    # Case A: two tracked seasons, only Season 01 exists on the server.
    def test_a_only_season_one_present_s2_does_not_match(self):
        rows = [
            make_row(101, "Multi Show", romaji="multi shou"),
            make_row(102, "Multi Show Season 2", romaji="multi shou 2", relation="Sequel"),
        ]
        seasons = infer_tracked_seasons(rows)
        # base has no indicator; franchise has an explicit Season 2 -> base = S1
        self.assertEqual(seasons[101], 1)
        self.assertEqual(seasons[102], 2)
        folder = cand("Multi Show (2023)", {1})
        r1 = match_record(rows[0], [folder], set(), seasons[101])
        r2 = match_record(rows[1], [folder], set(), seasons[102])
        self.assertEqual(r1.confidence, "confident")
        self.assertEqual(r2.confidence, "none")

    # Case B: both seasons present in one folder -> independent confident matches.
    def test_b_both_seasons_present_match_independently(self):
        rows = [
            make_row(201, "Multi Show", romaji="multi shou"),
            make_row(202, "Multi Show Season 2", romaji="multi shou 2", relation="Sequel"),
        ]
        seasons = infer_tracked_seasons(rows)
        self.assertEqual(seasons[201], 1)
        self.assertEqual(seasons[202], 2)
        folder = cand("Multi Show (2023)", {1, 2})
        r1 = match_record(rows[0], [folder], set(), seasons[201])
        r2 = match_record(rows[1], [folder], set(), seasons[202])
        self.assertEqual(r1.confidence, "confident")
        self.assertEqual(r2.confidence, "confident")

    # Case C: romaji/English trailing "2" suffix groups with the parent and
    # resolves to season 2 instead of an isolated None group.
    def test_c_trailing_digit_sequel_groups_with_parent(self):
        base = make_row(301, "Multi Show")
        sequel = make_row(302, "Multi Show 2", romaji="Multi Show 2", relation="Sequel")
        self.assertEqual(tracked_season_number(sequel), 2)
        # the sequel resolves to season 2 via its trailing digit; the base
        # entry keeps its original None (exact-title grouping, unchanged).
        seasons = infer_tracked_seasons([base, sequel])
        self.assertIsNone(seasons[301])
        self.assertEqual(seasons[302], 2)
        # a trailing-digit sequel is NOT ambiguous -> not in multi_season_ids
        self.assertEqual(multi_season_ids([base, sequel]), set())

    # Case D: multi-season row with an undeterminable season -> Needs Review,
    # never an automatic accept of a numbered folder.
    def test_d_unknown_season_in_multi_franchise_is_uncertain(self):
        base = make_row(401, "Multi Show")
        # finished sequel with no season indicator in its titles
        sequel = make_row(402, "Multi Show", relation="Sequel", airing_status="FINISHED")
        self.assertIsNone(tracked_season_number(sequel))
        multi = multi_season_ids([base, sequel])
        self.assertIn(402, multi)
        numbered = cand("Multi Show (2023)", {1})
        result = match_record(sequel, [numbered], set(), None, multi)
        self.assertEqual(result.confidence, "uncertain")
        self.assertEqual(result.path, "")

    # Case E: single-season shows keep the previous behavior (unknown season
    # still matches any folder; exact titles still match confidently).
    def test_e_single_season_behavior_unchanged(self):
        show = make_row(501, "Single Show")
        multi = multi_season_ids([show])
        self.assertEqual(multi, set())
        numbered = cand("Single Show (2023)", {1})
        self.assertTrue(candidate_supports_season(numbered, None, multi_season=False))
        result = match_record(show, [numbered], set(), None, multi)
        self.assertEqual(result.confidence, "confident")

    # Case F: Season 00 (specials) is separate from numbered seasons.
    def test_f_specials_season_zero_is_separate(self):
        folder_specials = cand("Multi Show 0 (2023)", {0})
        folder_one = cand("Multi Show 1 (2023)", {1})
        row_s1 = make_row(601, "Multi Show Season 1", year=2023)
        row_specials = make_row(602, "Multi Show 0", year=2023)
        # season-1 row must not be satisfied by a specials-only folder
        self.assertEqual(match_record(row_s1, [folder_specials], set(), 1).confidence, "none")
        # specials (season 0) matches only the specials folder
        self.assertEqual(match_record(row_specials, [folder_one], set(), 0).confidence, "none")
        self.assertEqual(match_record(row_specials, [folder_specials], set(), 0).confidence, "confident")

    # candidate_supports_season contract for the None-season gate.
    def test_none_season_gate_multi_vs_single(self):
        numbered = cand("X (2023)", {1})
        flat = cand("X", set())
        # multi-season franchise: None accepts only a flat folder
        self.assertFalse(candidate_supports_season(numbered, None, multi_season=True))
        self.assertTrue(candidate_supports_season(flat, None, multi_season=True))
        # single-season show: None accepts any folder (old behavior)
        self.assertTrue(candidate_supports_season(numbered, None, multi_season=False))
        self.assertTrue(candidate_supports_season(flat, None, multi_season=False))
        # known season: only membership matters, multi flag irrelevant
        self.assertTrue(candidate_supports_season(numbered, 1))
        self.assertFalse(candidate_supports_season(flat, 1))


if __name__ == "__main__":
    unittest.main()
