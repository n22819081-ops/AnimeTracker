from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from anime_tracker.services.anilist.cache import (
    AIRING_SCHEDULE_TTL,
    FINISHED_TTL,
    RELEASING_TTL,
    AniListCache,
    metadata_ttl,
)
from anime_tracker.services.anilist.models import CacheState, parse_media
from anime_tracker.services.anilist.service import AniListService

from anilist_helpers import NOW, FakeResponse, client_for, fixture, make_cache, media_response


class AniListCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = make_cache(Path(self.tmp.name) / "cache.db")
        self.cases = fixture("media_cases.json")

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, key="airing_tv"):
        media = parse_media(self.cases[key], NOW)
        self.cache.put_media(media, NOW)
        return media

    def test_fresh_cache_hit(self):
        self.put()
        record = self.cache.get_media(1002, NOW + timedelta(minutes=30))
        self.assertEqual(record.state, CacheState.FRESH)

    def test_expired_cache_hit_remains_available(self):
        self.put()
        record = self.cache.get_media(1002, NOW + RELEASING_TTL + timedelta(seconds=1))
        self.assertEqual(record.state, CacheState.STALE)
        self.assertEqual(record.media.anilist_id, 1002)

    def test_cache_miss(self):
        self.assertEqual(self.cache.get_media(9999, NOW).state, CacheState.MISS)

    def test_status_specific_expiration_policy(self):
        airing = parse_media(self.cases["airing_tv"], NOW)
        finished = parse_media(self.cases["finished_tv"], NOW)
        self.assertEqual(metadata_ttl(airing, NOW), RELEASING_TTL)
        self.assertEqual(metadata_ttl(finished, NOW), FINISHED_TTL)

    def test_corrupted_cache_entry_is_reported_not_deleted(self):
        self.put()
        with self.cache.connect() as connection:
            connection.execute("UPDATE anilist_media_cache SET normalized_payload_json='not-json' WHERE anilist_id=1002")
        record = self.cache.get_media(1002, NOW)
        self.assertEqual(record.state, CacheState.CORRUPT)
        with self.cache.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM anilist_media_cache").fetchone()[0], 1)

    def test_per_record_invalidation(self):
        self.put()
        self.assertTrue(self.cache.invalidate(1002, NOW))
        self.assertEqual(self.cache.get_media(1002, NOW).state, CacheState.STALE)
        self.assertFalse(self.cache.invalidate(9999, NOW))

    def test_failed_refresh_retains_old_data(self):
        media = self.put()
        self.cache.record_failure(1002, NOW + timedelta(hours=2), "TIMEOUT", "Timed out")
        record = self.cache.get_media(1002, NOW + timedelta(hours=2))
        self.assertEqual(record.media, media)
        self.assertEqual(record.failure_count, 1)
        self.assertEqual(record.last_error, "Timed out")

    def test_failed_forced_refresh_marks_fresh_record_stale(self):
        self.put()
        self.cache.record_failure(1002, NOW + timedelta(minutes=5), "TIMEOUT", "Timed out")
        self.assertEqual(self.cache.get_media(1002, NOW + timedelta(minutes=5)).state, CacheState.STALE)

    def test_full_test_cache_clear_preserves_unrelated_tracking_table(self):
        self.put()
        with self.cache.connect() as connection:
            connection.execute("CREATE TABLE tracked_titles(id INTEGER PRIMARY KEY, title TEXT)")
            connection.execute("INSERT INTO tracked_titles VALUES(1,'Keep')")
        self.assertEqual(self.cache.clear_test_profile(), 1)
        with self.cache.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM tracked_titles").fetchone()[0], 1)

    def test_non_test_profile_cannot_clear_all_cache(self):
        ordinary = AniListCache(self.cache.database_path)
        with self.assertRaises(PermissionError):
            ordinary.clear_test_profile()

    def test_cache_statistics(self):
        self.put("airing_tv")
        self.put("finished_tv")
        self.cache.record_failure(1002, NOW, "TIMEOUT", "Timed out")
        stats = self.cache.statistics(NOW + timedelta(hours=2))
        self.assertEqual((stats.total_records, stats.fresh_records, stats.stale_records, stats.failed_records), (2, 1, 1, 1))

    def test_bulk_cache_lookup_preserves_hits_misses_and_order(self):
        self.put("airing_tv")
        records = self.cache.get_many_media((9999, 1002, 9999), NOW)
        self.assertEqual(tuple(records), (9999, 1002))
        self.assertEqual(records[9999].state, CacheState.MISS)
        self.assertEqual(records[1002].state, CacheState.FRESH)

    def test_relation_cache_has_independent_expiration(self):
        self.put("finished_tv")
        fresh = self.cache.get_relations(1003, NOW + timedelta(days=6))
        stale = self.cache.get_relations(1003, NOW + timedelta(days=8))
        self.assertEqual((fresh.state, stale.state), (CacheState.FRESH, CacheState.STALE))
        self.assertEqual(len(stale.relations), 3)

    def test_schedule_cache_has_short_expiration_and_stale_data(self):
        media = parse_media(self.cases["airing_tv"], NOW)
        self.cache.put_airing_schedule(media.anilist_id, (media.next_airing_episode,), NOW)
        fresh = self.cache.get_airing_schedule_record(media.anilist_id, NOW + timedelta(minutes=10))
        stale = self.cache.get_airing_schedule_record(media.anilist_id, NOW + AIRING_SCHEDULE_TTL + timedelta(seconds=1))
        self.assertEqual((fresh.state, stale.state), (CacheState.FRESH, CacheState.STALE))
        self.assertEqual(stale.episodes[0].episode_number, 4)

    def test_empty_relation_and_schedule_snapshots_are_cached_not_misses(self):
        media = self.put("special")
        self.cache.put_airing_schedule(media.anilist_id, (), NOW)
        self.assertEqual(self.cache.get_relations(media.anilist_id, NOW).state, CacheState.FRESH)
        schedule = self.cache.get_airing_schedule_record(media.anilist_id, NOW)
        self.assertEqual(schedule.state, CacheState.FRESH)
        self.assertEqual(schedule.episodes, ())

    def test_connection_is_closed_after_operation(self):
        self.put()
        renamed = self.cache.database_path.with_name("renamed.db")
        self.cache.database_path.rename(renamed)
        self.assertTrue(renamed.exists())


class AniListServiceCacheBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = make_cache(Path(self.tmp.name) / "cache.db")
        self.cases = fixture("media_cases.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_fresh_get_uses_no_network(self):
        self.cache.put_media(parse_media(self.cases["finished_tv"], NOW), NOW)
        client, session = client_for([])
        result = AniListService(self.cache, client, clock=lambda: NOW).get_media(1003)
        self.assertTrue(result.cache_hit)
        self.assertFalse(result.network_request_performed)
        self.assertEqual(session.calls, [])

    def test_invalid_id_fails_without_network(self):
        client, session = client_for([])
        result = AniListService(self.cache, client, clock=lambda: NOW).get_media(0)
        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "INVALID_INPUT")
        self.assertEqual(session.calls, [])

    def test_force_refresh_performs_network_request(self):
        self.cache.put_media(parse_media(self.cases["finished_tv"], NOW), NOW)
        client, session = client_for([media_response(self.cases["finished_tv"])])
        result = AniListService(self.cache, client, clock=lambda: NOW).get_media(1003, force_refresh=True)
        self.assertTrue(result.success)
        self.assertTrue(result.network_request_performed)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(result.network_request_count, 1)
        with self.cache.connect() as connection:
            state = connection.execute("SELECT request_limit,remaining_requests FROM anilist_request_state").fetchone()
        self.assertEqual(tuple(state), (90, 89))

    def test_offline_stale_cache_fallback(self):
        self.cache.put_media(parse_media(self.cases["airing_tv"], NOW), NOW)
        later = NOW + timedelta(hours=2)
        client, _ = client_for([])
        result = AniListService(self.cache, client, clock=lambda: later).get_media(1002, offline=True)
        self.assertTrue(result.success)
        self.assertTrue(result.stale_cache_used)
        self.assertEqual(result.error_type, "OFFLINE_CACHE_USED")

    def test_network_failure_keeps_previous_metadata(self):
        original = parse_media(self.cases["airing_tv"], NOW)
        self.cache.put_media(original, NOW)
        later = NOW + timedelta(hours=2)
        client, _ = client_for([FakeResponse(503, {"data": None})])
        result = AniListService(self.cache, client, clock=lambda: later).get_media(1002)
        self.assertTrue(result.success)
        self.assertEqual(result.updated_data, original)
        self.assertEqual(result.error_type, "OFFLINE_CACHE_USED")
        self.assertEqual(self.cache.get_media(1002, later).media, original)

    def test_provider_outage_does_not_blank_cache(self):
        original = parse_media(self.cases["finished_tv"], NOW)
        self.cache.put_media(original, NOW)
        client, _ = client_for([FakeResponse(500, {"data": None})])
        service = AniListService(self.cache, client, clock=lambda: NOW + timedelta(days=31))
        service.get_media(1003)
        self.assertEqual(service.get_cache_status(1003).media.status, original.status)

    def test_mismatched_provider_identity_is_not_cached(self):
        client, _ = client_for([media_response(self.cases["finished_tv"])])
        service = AniListService(self.cache, client, clock=lambda: NOW)
        result = service.get_media(1002)
        self.assertFalse(result.success)
        self.assertEqual(result.error_type, "MALFORMED_RESPONSE")
        self.assertEqual(self.cache.get_media(1003, NOW).state, CacheState.MISS)


if __name__ == "__main__":
    unittest.main()
