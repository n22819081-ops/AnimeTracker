from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from anime_tracker.domain.enums import ReviewStatus, ServerPresence, TrackerWorkflowStatus
from anime_tracker.domain.legacy_adapter import adapt_archived_legacy_row, adapt_legacy_anime_row
from anime_tracker.domain.status_engine import decide_status


ROOT = Path(__file__).resolve().parents[1]
MODERN_ROOT = ROOT / "Modern Anime Tracker"
BACKUP_DB = MODERN_ROOT / "modernization_backups" / "20260801-230906-verified" / "sqlite_online" / "anime_tracker.db"
PROTOTYPE_DB = MODERN_ROOT / "migration_test" / "anime_tracker_modern_v1.db"


def sample_row(**changes):
    row = {
        "id": 1,
        "anilist_id": 100,
        "english_title": "Example",
        "romaji_title": "Example Romaji",
        "native_title": "Example Native",
        "alternate_titles": '["Alt"]',
        "format": "TV",
        "season": "SPRING",
        "year": 2026,
        "total_episodes": 12,
        "airing_status": "FINISHED",
        "tracker_status": "Finished / Ready to Add",
        "server_status": "Not Found",
        "review_reason": "No Jellyfin match found",
        "movie_availability": "unknown",
    }
    row.update(changes)
    return row


class LegacyAdapterTests(unittest.TestCase):
    def test_legacy_on_server_without_coverage_is_unknown_with_confirmation(self):
        adapted = adapt_legacy_anime_row(sample_row(tracker_status="On Server", server_status="On Server"))
        self.assertEqual(adapted.decision_input.server.presence, ServerPresence.UNKNOWN_COVERAGE)
        self.assertTrue(adapted.tracked_media.legacy_confirmation_preserved)
        self.assertTrue(adapted.warnings)
        self.assertEqual(decide_status(adapted.decision_input).workflow_status, TrackerWorkflowStatus.ON_SERVER)

    def test_legacy_not_found_is_not_needs_review(self):
        adapted = adapt_legacy_anime_row(sample_row())
        self.assertEqual(adapted.decision_input.server.presence, ServerPresence.NOT_FOUND)
        self.assertEqual(adapted.review_cases, ())
        self.assertEqual(decide_status(adapted.decision_input).workflow_status, TrackerWorkflowStatus.FINISHED_READY_TO_ADD)

    def test_legacy_needs_review_is_preserved(self):
        adapted = adapt_legacy_anime_row(sample_row(tracker_status="Needs Review", server_status="Needs Review", review_reason="Multiple possible matches"))
        self.assertEqual(adapted.review_cases[0].status, ReviewStatus.LEGACY_DATA_REVIEW)

    def test_legacy_missing_path_is_preserved(self):
        adapted = adapt_legacy_anime_row(sample_row(tracker_status="Needs Review", server_status="Missing - Needs Review"))
        self.assertEqual(adapted.decision_input.server.presence, ServerPresence.PATH_MISSING)
        self.assertEqual(adapted.review_cases[0].status, ReviewStatus.MISSING_CONFIRMED_PATH)

    def test_invalid_active_identity_is_rejected(self):
        with self.assertRaises(ValueError):
            adapt_legacy_anime_row(sample_row(anilist_id=0))

    @unittest.skipUnless(BACKUP_DB.exists(), "verified Milestone 1 backup is not present")
    def test_all_69_active_legacy_rows_are_representable_read_only(self):
        connection = sqlite3.connect(f"file:{BACKUP_DB.as_posix()}?mode=ro&immutable=1", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = list(connection.execute("SELECT * FROM anime ORDER BY id"))
            adapted = [adapt_legacy_anime_row(row) for row in rows]
        finally:
            connection.close()
        self.assertEqual(len(rows), 69)
        self.assertEqual(len(adapted), 69)
        self.assertEqual(len({item.tracked_media.identity.anilist_id for item in adapted}), 69)

    @unittest.skipUnless(PROTOTYPE_DB.exists(), "Milestone 1 migration prototype is not present")
    def test_all_orphan_rows_remain_preserved(self):
        connection = sqlite3.connect(f"file:{PROTOTYPE_DB.as_posix()}?mode=ro&immutable=1", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = list(connection.execute("SELECT * FROM archived_legacy_records ORDER BY id"))
            archived = [adapt_archived_legacy_row(row) for row in rows]
        finally:
            connection.close()
        self.assertEqual(len(rows), 421)
        self.assertEqual(len(archived), 421)
        self.assertTrue(all(item.requires_manual_review for item in archived))


if __name__ == "__main__":
    unittest.main()
