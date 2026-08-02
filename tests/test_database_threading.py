import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from anime_tracker.constants import TRACKER_ON_SERVER, TRACKER_READY
from anime_tracker.database import Database
from anime_tracker.models import AnimeRecord
from anime_tracker.scanner import match_record, scan_roots


def make_record() -> AnimeRecord:
    return AnimeRecord(
        english_title="Thread Test Anime",
        romaji_title="Thread Test Anime",
        native_title="",
        alternate_titles=[],
        anilist_id=424242,
        format="TV",
        season="",
        year=2026,
        total_episodes=12,
        airing_status="FINISHED",
        start_date="2026-01-01",
        expected_end_date="2026-03-31",
        cover_image_url="",
        anilist_url="https://anilist.co/anime/424242",
        tracker_status=TRACKER_READY,
    )


class DatabaseThreadingTests(unittest.TestCase):
    def test_database_write_from_worker_thread_does_not_share_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tracker.db"
            db = Database(db_path)
            errors: list[BaseException] = []

            def worker():
                try:
                    db.upsert_anime(make_record())
                    db.mark_event_sent("thread-test-event", "test", 424242)
                except BaseException as exc:
                    errors.append(exc)

            thread = threading.Thread(target=worker)
            thread.start()
            thread.join(timeout=10)

            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(len(db.rows()), 1)
            self.assertTrue(db.event_was_sent("thread-test-event"))
            self.assert_database_file_is_not_held_open(db_path)

    def test_jellyfin_scan_from_worker_thread_does_not_share_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tv_root = root / "tv"
            movie_root = root / "movies"
            tv_root.mkdir()
            movie_root.mkdir()
            (tv_root / "Thread Test Anime (2026)").mkdir()
            db_path = root / "tracker.db"
            db = Database(db_path)
            row_id = db.upsert_anime(make_record())
            db.set_settings({"tv_path": str(tv_root), "movie_path": str(movie_root)})
            errors: list[BaseException] = []

            def worker():
                try:
                    worker_db = Database(db_path)
                    settings = worker_db.get_settings()
                    candidates = scan_roots(settings["tv_path"], settings["movie_path"])
                    for row in worker_db.rows():
                        result = match_record(row, candidates)
                        if result.confidence == "confident":
                            worker_db.set_server_match(row["id"], "Found", TRACKER_ON_SERVER, result.path, row["manual_notes"])
                except BaseException as exc:
                    errors.append(exc)

            thread = threading.Thread(target=worker)
            thread.start()
            thread.join(timeout=10)

            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            updated = db.get(row_id)
            self.assertIsNotNone(updated)
            self.assertEqual(updated["tracker_status"], TRACKER_ON_SERVER)
            self.assertEqual(updated["server_status"], "Found")
            self.assert_database_file_is_not_held_open(db_path)

    def assert_database_file_is_not_held_open(self, db_path: Path) -> None:
        marker = db_path.with_suffix(".moved")
        db_path.rename(marker)
        marker.rename(db_path)
        connection = sqlite3.connect(db_path)
        try:
            connection.execute("SELECT 1").fetchone()
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
