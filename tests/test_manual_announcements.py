import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from anime_tracker.announcements import (
    LibraryChange,
    SnapshotItem,
    announcement_review_required,
    build_discord_messages,
    send_reviewed_batch,
)
from anime_tracker.constants import SERVER_NOT_FOUND, TRACKER_READY
from anime_tracker.database import Database
from anime_tracker.manual_announcements import (
    DuplicateManualAnnouncementError,
    ManualAnnouncementValidationError,
    build_manual_announcement,
    format_episode_set,
    parse_episode_expression,
)
from anime_tracker.models import AnimeRecord


def tv(title="Rick and Morty", year="2013", season="9", episodes="8"):
    return build_manual_announcement("TV Show", title, year, season, episodes)


def movie(title="Look Back", year="2024"):
    return build_manual_announcement("Movie", title, year)


class EpisodeParsingTests(unittest.TestCase):
    def test_single_episode(self):
        self.assertEqual(parse_episode_expression("8"), (8,))
        self.assertEqual(format_episode_set((8,)), "Episode 8")

    def test_episode_range(self):
        self.assertEqual(parse_episode_expression("7-8"), (7, 8))
        self.assertEqual(format_episode_set((7, 8)), "Episodes 7–8")

    def test_nonconsecutive_episodes(self):
        self.assertEqual(parse_episode_expression("1,3,5"), (1, 3, 5))
        self.assertEqual(format_episode_set((1, 3, 5)), "Episodes 1, 3, and 5")

    def test_mixed_range_and_episode(self):
        self.assertEqual(parse_episode_expression("1-4,8"), (1, 2, 3, 4, 8))
        self.assertEqual(format_episode_set((1, 2, 3, 4, 8)), "Episodes 1–4 and 8")

    def test_spaces_are_normalized(self):
        self.assertEqual(parse_episode_expression("1, 3, 5-7"), (1, 3, 5, 6, 7))

    def test_duplicates_are_removed_and_sorted(self):
        self.assertEqual(parse_episode_expression("3,1,1-3"), (1, 2, 3))
        self.assertEqual(format_episode_set((3, 1, 1, 2)), "Episodes 1–3")

    def test_invalid_episode_values_are_rejected(self):
        for value in ("", "0", "-1", "8-4", "abc", "1,,3"):
            with self.subTest(value=value):
                with self.assertRaises(ManualAnnouncementValidationError):
                    parse_episode_expression(value)


class ManualFormattingTests(unittest.TestCase):
    def test_tv_preview(self):
        self.assertEqual(tv().display_text, "Rick and Morty (2013) — Season 9, Episode 8")

    def test_multiple_episode_preview(self):
        self.assertEqual(tv(episodes="7-8").display_text, "Rick and Morty (2013) — Season 9, Episodes 7–8")

    def test_optional_tv_year_preview(self):
        self.assertEqual(tv(year="").display_text, "Rick and Morty — Season 9, Episode 8")

    def test_movie_preview(self):
        self.assertEqual(movie().display_text, "Look Back (2024) — Movie")

    def test_required_fields(self):
        invalid = [
            ("TV Show", "", "", "1", "1"),
            ("TV Show", "Show", "", "", "1"),
            ("TV Show", "Show", "", "1", ""),
            ("Movie", "", "2024", "", ""),
        ]
        for values in invalid:
            with self.subTest(values=values):
                with self.assertRaises(ManualAnnouncementValidationError):
                    build_manual_announcement(*values)

    def test_whitespace_is_trimmed(self):
        item = build_manual_announcement(" TV Show ", "  Rick   and Morty  ", " 2013 ", " 9 ", " 7 - 8 ")
        self.assertEqual(item.title, "Rick and Morty")
        self.assertEqual(item.display_text, "Rick and Morty (2013) — Season 9, Episodes 7–8")


class ManualQueueDatabaseTests(unittest.TestCase):
    def test_tv_and_movie_insertion(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            tv_id = db.add_manual_announcement(tv())
            movie_id = db.add_manual_announcement(movie())
            self.assertEqual([item.id for item in db.manual_announcements()], [tv_id, movie_id])

    def test_queue_persists_after_database_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tracker.db"
            Database(path).add_manual_announcement(tv())
            self.assertEqual(Database(path).manual_announcements()[0].display_text, tv().display_text)

    def test_duplicate_tv_is_prevented_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            db.add_manual_announcement(tv())
            with self.assertRaises(DuplicateManualAnnouncementError):
                db.add_manual_announcement(tv(title="  RICK  AND MORTY ", episodes="8,8"))

    def test_duplicate_movie_is_prevented(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            db.add_manual_announcement(movie())
            with self.assertRaises(DuplicateManualAnnouncementError):
                db.add_manual_announcement(movie(title="look back"))

    def test_edit_updates_same_row_and_does_not_conflict_with_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            item_id = db.add_manual_announcement(tv())
            db.update_manual_announcement(item_id, tv(episodes="8-9"))
            entries = db.manual_announcements()
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].id, item_id)
            self.assertEqual(entries[0].episodes, (8, 9))

    def test_edit_cannot_collide_with_another_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            first = db.add_manual_announcement(tv(episodes="8"))
            second = db.add_manual_announcement(tv(episodes="9"))
            with self.assertRaises(DuplicateManualAnnouncementError):
                db.update_manual_announcement(second, tv(episodes="8"))
            self.assertEqual({item.id for item in db.manual_announcements()}, {first, second})

    def test_removing_deletes_only_selected_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            first = db.add_manual_announcement(tv())
            second = db.add_manual_announcement(movie())
            db.delete_manual_announcements([first])
            self.assertEqual([item.id for item in db.manual_announcements()], [second])

    def test_local_title_suggestions_survive_queue_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            item_id = db.add_manual_announcement(movie())
            db.delete_manual_announcements([item_id])
            self.assertEqual(db.manual_title_suggestions("MOVIE"), [("Look Back", 2024)])

    def test_queue_does_not_change_tracker_or_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            record = AnimeRecord("Tracked", "Tracked", "", [], 99, "TV", "SPRING", 2024, 12, "FINISHED", "", "", "", "", TRACKER_READY)
            row_id = db.upsert_anime(record)
            snapshot = [SnapshotItem("MOVIE", "i:\\movies\\existing", "", "Existing")]
            db.replace_announcement_snapshot(snapshot)
            db.add_manual_announcement(movie())
            row = db.get(row_id)
            self.assertEqual(row["tracker_status"], TRACKER_READY)
            self.assertEqual(row["server_status"], SERVER_NOT_FOUND)
            self.assertEqual(db.get_announcement_snapshot(), snapshot)

    def test_fresh_database_contains_queue_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            with db.connect() as connection:
                table = connection.execute("SELECT name FROM sqlite_master WHERE name='manual_announcement_queue'").fetchone()
            self.assertIsNotNone(table)

    def test_existing_database_migrates_queue_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tracker.db"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE legacy(value TEXT)")
            connection.execute("INSERT INTO legacy VALUES('kept')")
            connection.commit()
            connection.close()
            with patch("anime_tracker.database.BACKUP_DIR", Path(tmp) / "backups"):
                db = Database(path)
            with db.connect() as connection:
                self.assertEqual(connection.execute("SELECT value FROM legacy").fetchone()[0], "kept")
                self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name='manual_announcement_queue'").fetchone())


class ManualQueueSendTests(unittest.TestCase):
    def test_only_manual_items_require_review(self):
        self.assertTrue(announcement_review_required([], [tv()]))
        self.assertFalse(announcement_review_required([], []))

    def test_automatic_and_manual_messages_group_together(self):
        changes = [
            LibraryChange("added", "SEASON", "Automatic Show", seasons=(2,)),
            LibraryChange("added", "TV_EPISODE", "Rick and Morty", 2013, custom_display=tv().display_text),
            LibraryChange("added", "MOVIE", "Look Back", 2024, custom_display=movie().display_text),
        ]
        message = "\n".join(build_discord_messages(changes))
        self.assertIn("TV Shows", message)
        self.assertIn(tv().display_text, message)
        self.assertIn("Movies", message)
        self.assertIn("Look Back (2024)", message)

    def test_success_removes_selected_and_leaves_unchecked(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            selected = db.add_manual_announcement(tv())
            unchecked = db.add_manual_announcement(movie())
            self.assertTrue(send_reviewed_batch(db, "secret", [LibraryChange("added", "TV_EPISODE", "Rick", custom_display=tv().display_text)], [], sender=lambda *_args: True, manual_queue_ids=[selected]))
            self.assertEqual([item.id for item in db.manual_announcements()], [unchecked])

    def test_discord_failure_and_partial_failure_remove_nothing(self):
        for sender in (lambda *_args: False, Mock(return_value=False)):
            with self.subTest(sender=sender):
                with tempfile.TemporaryDirectory() as tmp:
                    db = Database(Path(tmp) / "tracker.db")
                    item_id = db.add_manual_announcement(tv())
                    self.assertFalse(send_reviewed_batch(db, "secret", [LibraryChange("added", "TV_EPISODE", "Rick", custom_display=tv().display_text)], [], sender=sender, manual_queue_ids=[item_id]))
                    self.assertEqual([item.id for item in db.manual_announcements()], [item_id])
                    self.assertFalse(db.has_announcement_baseline())

    def test_no_selected_items_remove_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            item_id = db.add_manual_announcement(tv())
            self.assertFalse(send_reviewed_batch(db, "secret", [], [], sender=lambda *_args: True, manual_queue_ids=[]))
            self.assertEqual([item.id for item in db.manual_announcements()], [item_id])

    def test_cancel_equivalent_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            item_id = db.add_manual_announcement(tv())
            self.assertEqual([item.id for item in db.manual_announcements()], [item_id])
            self.assertFalse(db.has_announcement_baseline())


if __name__ == "__main__":
    unittest.main()
