import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from anime_tracker.announcements import (
    LibraryChange,
    LibraryInventoryError,
    SILENT_MESSAGE_FLAG,
    SnapshotItem,
    build_discord_messages,
    build_library_snapshot,
    default_selected,
    detect_changes,
    format_seasons,
    parse_folder_name,
    parse_season_number,
    send_silent_announcements,
    send_reviewed_batch,
    shared_announcements_apply_to_scan,
)
from anime_tracker.config import NotificationConfig
from anime_tracker.database import Database
from anime_tracker.path_utils import normalize_windows_path


def item(item_type, path, title, year=None, season=None, parent=""):
    return SnapshotItem(item_type, normalize_windows_path(path), normalize_windows_path(parent) if parent else "", title, year, season, path)


class InventoryTests(unittest.TestCase):
    def test_inventory_contains_shows_movies_and_recognized_seasons_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tv = root / "TV"
            movies = root / "Movies"
            (tv / "Dr. STONE (2019)" / "Season 01").mkdir(parents=True)
            (tv / "Dr. STONE (2019)" / "S02").mkdir()
            (tv / "Dr. STONE (2019)" / "Extras").mkdir()
            (movies / "Look Back (2024)").mkdir(parents=True)
            snapshot = build_library_snapshot(str(tv), str(movies))
            self.assertEqual([row.item_type for row in snapshot].count("TV_SHOW"), 1)
            self.assertEqual([row.item_type for row in snapshot].count("MOVIE"), 1)
            self.assertEqual(sorted(row.season_number for row in snapshot if row.item_type == "SEASON"), [1, 2])

    def test_season_folder_conventions(self):
        self.assertEqual([parse_season_number(value) for value in ("Season 01", "Season 1", "S01", "01")], [1, 1, 1, 1])
        self.assertIsNone(parse_season_number("Specials"))

    def test_folder_title_and_trailing_year_are_parsed(self):
        self.assertEqual(parse_folder_name("Dr. STONE (2019)"), ("Dr. STONE", 2019))
        self.assertEqual(parse_folder_name("No Year"), ("No Year", None))

    def test_unavailable_tv_root_fails_complete_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            movies = Path(tmp) / "Movies"
            movies.mkdir()
            with self.assertRaises(LibraryInventoryError):
                build_library_snapshot(str(Path(tmp) / "Missing"), str(movies))

    def test_unavailable_movie_root_fails_complete_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            tv = Path(tmp) / "TV"
            tv.mkdir()
            with self.assertRaises(LibraryInventoryError):
                build_library_snapshot(str(tv), str(Path(tmp) / "Missing"))


class ChangeDetectionTests(unittest.TestCase):
    def test_new_and_removed_show_and_movie_are_detected(self):
        old = [item("TV_SHOW", r"I:\TV\Old", "Old"), item("MOVIE", r"I:\Movies\Gone", "Gone", 2020)]
        new = [item("TV_SHOW", r"I:\TV\New", "New"), item("MOVIE", r"I:\Movies\Look Back", "Look Back", 2024)]
        changes = detect_changes(old, new)
        values = {(row.change_type, row.item_type, row.title) for row in changes}
        self.assertEqual(values, {("removed", "TV_SHOW", "Old"), ("removed", "MOVIE", "Gone"), ("added", "TV_SHOW", "New"), ("added", "MOVIE", "Look Back")})

    def test_new_and_removed_seasons_are_grouped(self):
        show = item("TV_SHOW", r"I:\TV\Stone", "Stone")
        old = [show, item("SEASON", r"I:\TV\Stone\Season 1", "Stone", season=1, parent=show.original_path), item("SEASON", r"I:\TV\Stone\Season 3", "Stone", season=3, parent=show.original_path)]
        new = [show, item("SEASON", r"I:\TV\Stone\Season 2", "Stone", season=2, parent=show.original_path), item("SEASON", r"I:\TV\Stone\Season 3", "Stone", season=3, parent=show.original_path)]
        changes = detect_changes(old, new)
        self.assertIn(LibraryChange("added", "SEASON", "Stone", None, (2,)), changes)
        self.assertIn(LibraryChange("removed", "SEASON", "Stone", None, (1,)), changes)

    def test_new_show_suppresses_redundant_seasons(self):
        show = item("TV_SHOW", r"I:\TV\New", "New")
        current = [show, item("SEASON", r"I:\TV\New\Season 1", "New", season=1, parent=show.original_path)]
        changes = detect_changes([], current)
        self.assertEqual(changes, [LibraryChange("added", "TV_SHOW", "New")])

    def test_removed_show_suppresses_redundant_seasons(self):
        show = item("TV_SHOW", r"I:\TV\Old", "Old")
        previous = [show, item("SEASON", r"I:\TV\Old\Season 1", "Old", season=1, parent=show.original_path)]
        self.assertEqual(detect_changes(previous, []), [LibraryChange("removed", "TV_SHOW", "Old")])

    def test_no_changes_returns_empty(self):
        snapshot = [item("MOVIE", r"I:\Movies\Same", "Same")]
        self.assertEqual(detect_changes(snapshot, snapshot), [])

    def test_paths_compare_case_insensitively_with_slashes_and_trailing_separator(self):
        old = [item("MOVIE", "I:/Movies/Look Back/", "Look Back")]
        new = [item("MOVIE", r"i:\movies\look back", "Look Back")]
        self.assertEqual(detect_changes(old, new), [])

    def test_season_display_formats(self):
        self.assertEqual(format_seasons([3]), "Season 3")
        self.assertEqual(format_seasons([4, 5]), "Seasons 4–5")
        self.assertEqual(format_seasons([1, 3, 5]), "Seasons 1, 3, and 5")


class DiscordAnnouncementTests(unittest.TestCase):
    def test_addition_and_removal_defaults(self):
        self.assertTrue(default_selected(LibraryChange("added", "MOVIE", "New"), True, False))
        self.assertFalse(default_selected(LibraryChange("removed", "MOVIE", "Old"), True, False))

    def test_unchecked_items_can_be_excluded_before_message_build(self):
        selected = [LibraryChange("added", "MOVIE", "Selected", 2024)]
        content = "\n".join(build_discord_messages(selected))
        self.assertIn("Selected", content)
        self.assertNotIn("Unchecked", content)

    @patch("anime_tracker.announcements.requests.post")
    def test_silent_flag_and_mentions_are_used(self, post):
        response = Mock()
        response.raise_for_status.return_value = None
        post.return_value = response
        self.assertTrue(send_silent_announcements("secret-webhook", [LibraryChange("added", "MOVIE", "Look Back", 2024)]))
        kwargs = post.call_args.kwargs
        self.assertNotIn("params", kwargs)
        self.assertEqual(kwargs["json"]["flags"], SILENT_MESSAGE_FLAG)
        self.assertIsInstance(kwargs["json"]["flags"], int)
        self.assertEqual(kwargs["json"]["allowed_mentions"], {"parse": []})

    @patch("anime_tracker.announcements.requests.post")
    def test_silent_disabled_omits_flags_from_json_payload(self, post):
        response = Mock()
        response.raise_for_status.return_value = None
        post.return_value = response
        self.assertTrue(send_silent_announcements("secret-webhook", [LibraryChange("added", "MOVIE", "Look Back")], send_silently=False))
        self.assertNotIn("flags", post.call_args.kwargs["json"])

    @patch("anime_tracker.announcements.requests.post")
    def test_every_split_message_has_silent_flag_in_json_payload(self, post):
        response = Mock()
        response.raise_for_status.return_value = None
        post.return_value = response
        changes = [LibraryChange("added", "MOVIE", f"Movie {index} " + "x" * 150) for index in range(30)]
        self.assertTrue(send_silent_announcements("secret-webhook", changes, send_silently=True))
        self.assertGreater(post.call_count, 1)
        for call in post.call_args_list:
            self.assertEqual(call.kwargs["json"].get("flags"), SILENT_MESSAGE_FLAG)
            self.assertNotIn("params", call.kwargs)

    @patch("anime_tracker.announcements.requests.post")
    def test_discord_failure_returns_false(self, post):
        import requests
        post.side_effect = requests.Timeout("secret must not be surfaced")
        self.assertFalse(send_silent_announcements("secret-webhook", [LibraryChange("added", "MOVIE", "Test")]))

    @patch("anime_tracker.announcements.requests.post")
    def test_partial_multi_message_failure_is_not_success(self, post):
        import requests
        ok = Mock()
        ok.raise_for_status.return_value = None
        post.side_effect = [ok, requests.ConnectionError("failed")]
        changes = [LibraryChange("added", "MOVIE", "A" * 1000), LibraryChange("removed", "MOVIE", "B" * 1000)]
        self.assertFalse(send_silent_announcements("secret-webhook", changes))
        self.assertEqual(post.call_count, 2)

    def test_messages_respect_safe_content_length(self):
        changes = [LibraryChange("added", "MOVIE", f"Movie {index} " + "x" * 150) for index in range(30)]
        messages = build_discord_messages(changes)
        self.assertGreater(len(messages), 1)
        self.assertTrue(all(len(message) <= 1900 for message in messages))

    def test_nothing_selected_produces_no_messages_and_no_send(self):
        self.assertEqual(build_discord_messages([]), [])
        self.assertFalse(send_silent_announcements("secret-webhook", []))

    def test_only_manual_scan_is_eligible(self):
        self.assertTrue(shared_announcements_apply_to_scan(False))
        self.assertFalse(shared_announcements_apply_to_scan(True))

    def test_failed_send_does_not_update_baseline(self):
        database = Mock()
        result = send_reviewed_batch(database, "secret", [LibraryChange("added", "MOVIE", "New")], [], sender=lambda *_args: False)
        self.assertFalse(result)
        database.replace_announcement_snapshot.assert_not_called()

    def test_successful_send_stores_complete_current_snapshot(self):
        database = Mock()
        current = [item("MOVIE", r"I:\Movies\Selected", "Selected"), item("MOVIE", r"I:\Movies\Unchecked", "Unchecked")]
        result = send_reviewed_batch(database, "secret", [LibraryChange("added", "MOVIE", "Selected")], current, sender=lambda *_args: True)
        self.assertTrue(result)
        database.commit_announcement_send.assert_called_once_with(current, [])

    def test_reviewed_batch_passes_silent_setting_to_sender(self):
        database = Mock()
        sender = Mock(return_value=True)
        selected = [LibraryChange("added", "MOVIE", "Selected")]
        self.assertTrue(send_reviewed_batch(database, "secret", selected, [], sender=sender, send_silently=False))
        sender.assert_called_once_with("secret", selected, False)

    def test_nothing_selected_does_not_send_or_store(self):
        database = Mock()
        sender = Mock(return_value=True)
        self.assertFalse(send_reviewed_batch(database, "secret", [], [], sender=sender))
        sender.assert_not_called()
        database.replace_announcement_snapshot.assert_not_called()


class SnapshotDatabaseTests(unittest.TestCase):
    def test_fresh_database_has_snapshot_schema_and_no_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            with db.connect() as connection:
                table = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jellyfin_announcement_snapshot'").fetchone()
            self.assertIsNotNone(table)
            self.assertFalse(db.has_announcement_baseline())

    def test_creating_first_baseline_persists_without_notification_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            snapshot = [item("MOVIE", r"I:\Movies\Look Back (2024)", "Look Back", 2024)]
            db.replace_announcement_snapshot(snapshot)
            self.assertTrue(db.has_announcement_baseline())
            self.assertEqual(db.get_announcement_snapshot(), snapshot)
            with db.connect() as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM notification_events").fetchone()[0], 0)

    def test_cancel_equivalent_stores_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            self.assertFalse(db.has_announcement_baseline())
            self.assertEqual(db.get_announcement_snapshot(), [])

    def test_complete_snapshot_replacement_includes_unannounced_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            complete = [item("MOVIE", r"I:\Movies\Selected", "Selected"), item("MOVIE", r"I:\Movies\Unchecked", "Unchecked")]
            db.replace_announcement_snapshot(complete)
            self.assertEqual({row.title for row in db.get_announcement_snapshot()}, {"Selected", "Unchecked"})

    def test_empty_successful_snapshot_is_still_a_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            db.replace_announcement_snapshot([])
            self.assertTrue(db.has_announcement_baseline())

    def test_existing_database_migrates_without_losing_existing_table(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tracker.db"
            connection = sqlite3.connect(path)
            try:
                connection.execute("CREATE TABLE legacy(value TEXT)")
                connection.execute("INSERT INTO legacy VALUES('kept')")
                connection.commit()
            finally:
                connection.close()
            db = Database(path)
            with db.connect() as connection:
                self.assertEqual(connection.execute("SELECT value FROM legacy").fetchone()[0], "kept")
                self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name='jellyfin_announcement_snapshot'").fetchone())


class ConfigSeparationTests(unittest.TestCase):
    def test_shared_defaults_are_safe(self):
        config = NotificationConfig()
        self.assertFalse(config.shared_announcements_enabled)
        self.assertTrue(config.shared_send_silently)
        self.assertTrue(config.shared_announce_additions)
        self.assertFalse(config.shared_announce_removals)

    def test_shared_webhook_is_separate_from_private_webhook(self):
        config = NotificationConfig(discord_webhook_url="private", shared_discord_webhook_url="shared")
        self.assertEqual(config.discord_webhook_url, "private")
        self.assertEqual(config.shared_discord_webhook_url, "shared")


if __name__ == "__main__":
    unittest.main()
