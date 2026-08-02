from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from anime_tracker.domain.enums import AniListStatus, MediaKind, RelationType
from anime_tracker.services.anilist.errors import AniListErrorType, AniListServiceError
from anime_tracker.services.anilist.models import DigitalAvailability, media_to_payload, parse_media
from anime_tracker.services.anilist.search import AniListSearch, parse_search_input
from anime_tracker.services.anilist.service import AniListService

from anilist_helpers import NOW, client_for, fixture, make_cache, media_response, page_response


class AniListModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = fixture("media_cases.json")

    def test_media_parsing_preserves_typed_fields(self):
        media = parse_media(self.cases["upcoming_tv"], NOW)
        self.assertEqual(media.anilist_id, 1001)
        self.assertEqual(media.mal_id, 9001)
        self.assertEqual(media.title.primary, "Skyward Days")
        self.assertEqual(media.title.variants, ("Skyward Days", "Sora no Hibi", "空の日々", "Days of Sky"))
        self.assertEqual(media.media_format, MediaKind.TV)
        self.assertEqual(media.status, AniListStatus.NOT_YET_RELEASED)
        self.assertEqual(media.start_date, date(2027, 10, 3))
        self.assertEqual(media.digital_availability, DigitalAvailability.UNKNOWN)

    def test_missing_optional_fields_and_unknown_values(self):
        media = parse_media(self.cases["missing_fields"], NOW)
        self.assertEqual(media.title.primary, "Nameless Signal")
        self.assertEqual(media.media_format, MediaKind.UNKNOWN)
        self.assertEqual(media.status, AniListStatus.UNKNOWN)
        self.assertIsNone(media.episode_count)
        self.assertIsNone(media.start_date)

    def test_all_supported_media_kinds_parse(self):
        expected = {"movie": MediaKind.MOVIE, "ova": MediaKind.OVA, "ona": MediaKind.ONA, "special": MediaKind.SPECIAL}
        for key, kind in expected.items():
            with self.subTest(key=key):
                self.assertEqual(parse_media(self.cases[key], NOW).media_format, kind)

    def test_adult_content_flag_is_preserved(self):
        self.assertTrue(parse_media(self.cases["adult"], NOW).is_adult)

    def test_next_airing_episode_is_utc_and_typed(self):
        item = parse_media(self.cases["airing_tv"], NOW).next_airing_episode
        self.assertIsNotNone(item)
        self.assertIsNotNone(item.airing_at.tzinfo)
        self.assertEqual(item.episode_number, 4)

    def test_relations_preserve_real_ids_and_types(self):
        media = parse_media(self.cases["finished_tv"], NOW)
        self.assertEqual({item.target_anilist_id for item in media.relations}, {1002, 1004, 1005})
        self.assertEqual({item.relation_type for item in media.relations}, {RelationType.SEQUEL, RelationType.MOVIE, RelationType.OVA})

    def test_normalized_cache_payload_round_trip(self):
        original = parse_media(self.cases["airing_tv"], NOW)
        restored = parse_media(media_to_payload(original), NOW)
        self.assertEqual(restored.anilist_id, original.anilist_id)
        self.assertEqual(restored.relations, original.relations)

    def test_invalid_media_payload_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_media({"title": {}}, NOW)


class SearchInputTests(unittest.TestCase):
    def test_exact_anilist_id(self):
        self.assertEqual(parse_search_input(1001).kind, "ANILIST_ID")
        self.assertEqual(parse_search_input("1001").value, 1001)

    def test_anilist_url(self):
        parsed = parse_search_input("https://anilist.co/anime/1001/skyward-days")
        self.assertEqual((parsed.kind, parsed.value), ("ANILIST_ID", 1001))

    def test_mal_id(self):
        self.assertEqual(parse_search_input("MAL: 9001").kind, "MAL_ID")

    def test_title_input(self):
        self.assertEqual(parse_search_input("Clockwork Harbor").kind, "TITLE")

    def test_invalid_input(self):
        for value in ("", "https://example.test/anime/1", 0):
            with self.subTest(value=value), self.assertRaises(AniListServiceError) as error:
                parse_search_input(value)
            self.assertEqual(error.exception.error_type, AniListErrorType.INVALID_INPUT)


class SearchServiceTests(unittest.TestCase):
    def setUp(self):
        self.cases = fixture("media_cases.json")

    def test_exact_id_lookup_uses_media_query(self):
        client, session = client_for([media_response(self.cases["upcoming_tv"])])
        result = AniListSearch(client).exact_lookup(parse_search_input(1001))
        self.assertEqual(result.anilist_id, 1001)
        self.assertEqual(session.calls[0][1]["json"]["variables"], {"id": 1001})

    def test_mal_lookup_uses_mal_variable(self):
        client, session = client_for([media_response(self.cases["upcoming_tv"])])
        AniListSearch(client).exact_lookup(parse_search_input("MAL:9001"))
        self.assertEqual(session.calls[0][1]["json"]["variables"], {"malId": 9001})

    def test_title_search_filters_and_paginates(self):
        client, session = client_for([
            page_response([self.cases["airing_tv"]], has_next=True, page=2),
            page_response([self.cases["finished_tv"]], has_next=False, page=3),
        ])
        results = AniListSearch(client).search_title(
            "Clockwork", year=2026, media_format=MediaKind.TV, season="summer", page=2, per_page=10, limit=20,
        )
        self.assertEqual([item.anilist_id for item in results], [1002, 1003])
        first = session.calls[0][1]["json"]["variables"]
        self.assertEqual((first["year"], first["format"], first["season"], first["page"]), (2026, "TV", "SUMMER", 2))
        self.assertEqual(session.calls[1][1]["json"]["variables"]["page"], 3)

    def test_duplicate_results_are_suppressed(self):
        client, _ = client_for([page_response([self.cases["airing_tv"], self.cases["airing_tv"]])])
        results = AniListSearch(client).search_title("Clockwork")
        self.assertEqual(len(results), 1)

    def test_no_results(self):
        client, _ = client_for([page_response([])])
        self.assertEqual(AniListSearch(client).search_title("Nothing"), ())

    def test_configurable_limit_is_not_fixed_at_eight(self):
        rows = [dict(self.cases["upcoming_tv"], id=2000 + index) for index in range(12)]
        client, _ = client_for([page_response(rows)])
        self.assertEqual(len(AniListSearch(client).search_title("Sky", limit=12)), 12)

    def test_offline_search_matches_synonyms(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = make_cache(Path(tmp) / "cache.db")
            cache.put_media(parse_media(self.cases["upcoming_tv"], NOW), NOW)
            client, _ = client_for([])
            service = AniListService(cache, client, clock=lambda: NOW)
            result = service.search_media("Days of Sky", offline=True)
            self.assertEqual([item.anilist_id for item in result], [1001])

    def test_multiple_media_page_retrieval_is_typed_and_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = make_cache(Path(tmp) / "cache.db")
            client, session = client_for([page_response([self.cases["upcoming_tv"], self.cases["airing_tv"]])])
            service = AniListService(cache, client, clock=lambda: NOW)
            values = service.get_media_page([1001, 1002, 1001], page=1, per_page=25)
            self.assertEqual([item.anilist_id for item in values], [1001, 1002])
            variables = session.calls[0][1]["json"]["variables"]
            self.assertEqual(variables, {"ids": [1001, 1002], "page": 1, "perPage": 25})
            self.assertEqual(cache.get_media(1002, NOW).state.value, "FRESH")


if __name__ == "__main__":
    unittest.main()
