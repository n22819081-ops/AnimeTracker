from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from anime_tracker.services.anilist.cancellation import CancellationToken
from anime_tracker.services.anilist.models import AniListRefreshResult, BatchState
from anime_tracker.services.anilist.refresh import build_refresh_batch
from anime_tracker.services.anilist.service import AniListService

from anilist_helpers import NOW, client_for, fixture, make_cache, media_response


def success(media_id, *, cache=False, network=True):
    return AniListRefreshResult(media_id, True, cache, network, None, started_at=NOW, completed_at=NOW)


def failure(media_id, error="TIMEOUT"):
    return AniListRefreshResult(media_id, False, False, True, None, error, "Failed safely", True, started_at=NOW, completed_at=NOW)


class RefreshBatchLogicTests(unittest.TestCase):
    def build(self, ids, callback, **kwargs):
        return build_refresh_batch(ids, callback, started_at=NOW, completed_at=lambda: NOW, batch_id="batch-test", **kwargs)

    def test_all_success(self):
        batch = self.build([1, 2], lambda item: success(item))
        self.assertEqual((batch.state, batch.succeeded, batch.failed, batch.total), (BatchState.SUCCESS, 2, 0, 2))

    def test_partial_success(self):
        batch = self.build([1, 2], lambda item: success(item) if item == 1 else failure(item))
        self.assertEqual(batch.state, BatchState.PARTIAL_FAILURE)
        self.assertTrue(batch.partial_success)

    def test_all_failure(self):
        batch = self.build([1, 2], failure)
        self.assertEqual((batch.state, batch.succeeded, batch.failed), (BatchState.FAILED, 0, 2))

    def test_cache_only_batch(self):
        batch = self.build([1, 2], lambda item: success(item, cache=True, network=False))
        self.assertEqual((batch.cache_hits, batch.network_requests), (2, 0))

    def test_mixed_cache_and_network(self):
        batch = self.build([1, 2], lambda item: success(item, cache=item == 1, network=item == 2))
        self.assertEqual((batch.cache_hits, batch.network_requests), (1, 1))

    def test_repeated_ids_are_deduplicated_in_first_seen_order(self):
        batch = self.build([2, 1, 2, 1], success)
        self.assertEqual(batch.requested_anilist_ids, (2, 1))
        self.assertEqual(batch.total, 2)

    def test_archived_titles_are_excluded_unless_requested(self):
        ordinary = self.build([1, 2, 3], success, archived_ids={2})
        included = self.build([1, 2, 3], success, archived_ids={2}, include_archived=True)
        self.assertEqual(ordinary.requested_anilist_ids, (1, 3))
        self.assertEqual(included.requested_anilist_ids, (1, 2, 3))

    def test_cancellation_preserves_completed_results(self):
        token = CancellationToken()
        def callback(item):
            result = success(item)
            token.cancel()
            return result
        batch = self.build([1, 2, 3], callback, token=token)
        self.assertEqual((batch.succeeded, batch.canceled_count), (1, 2))
        self.assertEqual(batch.results[0].anilist_id, 1)
        self.assertTrue(all(item.canceled for item in batch.results[1:]))

    def test_42_successes_and_27_failures_is_partial_not_success(self):
        batch = self.build(range(1, 70), lambda item: success(item) if item <= 42 else failure(item))
        self.assertEqual((batch.succeeded, batch.failed), (42, 27))
        self.assertEqual(batch.state, BatchState.PARTIAL_FAILURE)
        self.assertNotEqual(batch.state, BatchState.SUCCESS)

    def test_error_summary_is_accurate(self):
        batch = self.build([1, 2, 3], lambda item: failure(item, "TIMEOUT" if item < 3 else "NOT_FOUND"))
        self.assertEqual(dict(batch.error_summary), {"NOT_FOUND": 1, "TIMEOUT": 2})

    def test_usable_stale_fallback_is_reported_as_partial_not_full_success(self):
        degraded = AniListRefreshResult(
            1, True, True, True, None, "OFFLINE_CACHE_USED", "Cached data retained", True,
            started_at=NOW, completed_at=NOW, stale_cache_used=True,
        )
        batch = self.build([1], lambda _item: degraded)
        self.assertEqual(batch.state, BatchState.PARTIAL_FAILURE)
        self.assertTrue(batch.partial_success)
        self.assertEqual(batch.succeeded, 1)


class RefreshBatchServiceTests(unittest.TestCase):
    def test_mixed_batch_uses_cache_network_and_persists_items(self):
        cases = fixture("media_cases.json")
        with tempfile.TemporaryDirectory() as tmp:
            cache = make_cache(Path(tmp) / "cache.db")
            from anime_tracker.services.anilist.models import parse_media
            cache.put_media(parse_media(cases["finished_tv"], NOW), NOW)
            client, session = client_for([media_response(cases["airing_tv"])])
            service = AniListService(cache, client, clock=lambda: NOW)
            batch = service.refresh_batch([1003, 1002], batch_id="persisted")
            self.assertEqual((batch.cache_hits, batch.network_requests, batch.succeeded), (1, 1, 2))
            connection = sqlite3.connect(cache.database_path)
            try:
                self.assertEqual(connection.execute("SELECT result FROM anilist_refresh_batches WHERE batch_key='persisted'").fetchone()[0], "SUCCESS")
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM anilist_refresh_items WHERE batch_key='persisted'").fetchone()[0], 2)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
