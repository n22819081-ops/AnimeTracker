from __future__ import annotations

import unittest

from anime_tracker.seasons import (
    FranchiseEntry,
    find_franchise_entries,
    mark_tracked_entries,
)


class FakeClient:
    """Returns canned media nodes by id, mirroring AniListClient.get_by_id."""

    def __init__(self, media: dict[int, dict]) -> None:
        self.media = media

    def get_by_id(self, anilist_id: int) -> dict:
        return self.media[anilist_id]


def node(node_id: int, romaji: str, fmt: str = "TV", season=None, status="FINISHED") -> dict:
    return {
        "id": node_id,
        "format": fmt,
        "status": status,
        "season": season,
        "title": {"romaji": romaji, "english": None, "native": None},
    }


def relations(*edges) -> dict:
    return {"relations": {"edges": list(edges)}}


def edge(relation_type: str, target: dict) -> dict:
    return {"relationType": relation_type, "node": target}


class FranchiseDiscoveryTests(unittest.TestCase):
    def test_follows_season_chain_beyond_one_level(self):
        client = FakeClient(
            {
                1: relations(edge("SEQUEL", node(2, "Show S2", season=2))),
                2: relations(edge("SEQUEL", node(3, "Show S3", season=3))),
                3: relations(),
            }
        )
        entries = find_franchise_entries(client, 1)
        self.assertEqual([entry.anilist_id for entry in entries], [2, 3])
        self.assertEqual({entry.category for entry in entries}, {"Next Season"})

    def test_movie_sequel_is_categorized_as_movie(self):
        client = FakeClient(
            {
                1: relations(edge("SEQUEL", node(20, "Movie", fmt="MOVIE"))),
                20: relations(),
            }
        )
        entries = find_franchise_entries(client, 1)
        self.assertEqual(entries[0].category, "Movie")
        self.assertEqual(entries[0].format, "MOVIE")

    def test_specials_included_by_default_but_not_followed(self):
        client = FakeClient(
            {
                1: relations(edge("SIDE_STORY", node(30, "Specials", fmt="SPECIAL"))),
                30: relations(edge("SIDE_STORY", node(31, "More Specials", fmt="SPECIAL"))),
                31: relations(),
            }
        )
        entries = find_franchise_entries(client, 1)
        # SIDE_STORY is not a season relation: the special is listed (default
        # include_specials) but its own relations are not walked.
        self.assertEqual([entry.anilist_id for entry in entries], [30])
        self.assertEqual(entries[0].category, "Special")
        entries_no_specials = find_franchise_entries(client, 1, include_specials=False)
        self.assertEqual(entries_no_specials, [])
        # A season-typed edge to a special IS followed (spun-off specials chain).
        client2 = FakeClient(
            {
                1: relations(edge("SPIN_OFF", node(30, "Specials", fmt="SPECIAL"))),
                30: relations(edge("SPIN_OFF", node(31, "Specials 2", fmt="SPECIAL"))),
                31: relations(),
            }
        )
        entries2 = find_franchise_entries(client2, 1, include_specials=True)
        self.assertEqual([entry.anilist_id for entry in entries2], [30, 31])

    def test_excludes_adaptation_and_character_relations(self):
        client = FakeClient(
            {
                1: relations(
                    edge("ADAPTATION", node(40, "Manga", fmt="TV")),
                    edge("CHARACTER", node(41, "Crossover", fmt="SPECIAL")),
                ),
                40: relations(),
                41: relations(),
            }
        )
        self.assertEqual(find_franchise_entries(client, 1), [])

    def test_no_relations_yields_empty_list(self):
        client = FakeClient({1: relations()})
        self.assertEqual(find_franchise_entries(client, 1), [])

    def test_mark_tracked_flags_added_and_row_id(self):
        entries = [
            FranchiseEntry(anilist_id=10, title="A"),
            FranchiseEntry(anilist_id=11, title="B"),
        ]
        mark_tracked_entries(entries, {10}, {10: 99})
        self.assertTrue(entries[0].added)
        self.assertEqual(entries[0].row_id, 99)
        self.assertFalse(entries[1].added)
        self.assertIsNone(entries[1].row_id)

    def test_display_label_includes_season(self):
        entry = FranchiseEntry(anilist_id=1, title="Show", season=3)
        self.assertEqual(entry.display_label(), "Show (Season 3)")


if __name__ == "__main__":
    unittest.main()
