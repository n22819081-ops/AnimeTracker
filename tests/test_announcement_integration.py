import unittest
from pathlib import Path


class AnnouncementIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).parents[1] / "src" / "anime_tracker" / "app.py").read_text(encoding="utf-8")

    def test_settings_has_dedicated_announcements_tab(self):
        self.assertIn('notebook.add(announcements, text="Announcements")', self.source)
        self.assertIn('text="Enable shared Discord announcements"', self.source)
        self.assertIn('show="*"', self.source)
        self.assertIn("Suppresses Discord push/banner notifications. The message still appears normally in the channel and may create an unread badge.", self.source)
        self.assertIn('text="Manual Announcement Queue"', self.source)
        self.assertIn('text="Add to Queue"', self.source)
        self.assertIn('text="Edit Selected"', self.source)
        self.assertIn('text="Remove Selected"', self.source)

    def test_manual_scan_wires_announcement_review(self):
        scan_section = self.source.split("def scan_jellyfin", 1)[1].split("def _review_library_announcements", 1)[0]
        self.assertIn("shared_announcements_apply_to_scan(silent)", scan_section)
        self.assertIn("_review_library_announcements", scan_section)

    def test_check_all_does_not_wire_shared_announcements(self):
        section = self.source.split("def check_all", 1)[1].split("def scan_jellyfin", 1)[0]
        self.assertNotIn("shared_announcements", section)
        self.assertNotIn("build_library_snapshot", section)
        self.assertNotIn("manual_announcements", section)

    def test_scheduled_check_does_not_wire_shared_announcements(self):
        section = self.source.split("def silent_check", 1)[1]
        self.assertNotIn("shared_announcements", section)
        self.assertNotIn("build_library_snapshot", section)
        self.assertNotIn("manual_announcements", section)

    def test_startup_does_not_process_manual_queue(self):
        section = self.source.split("class AnimeTrackerApp", 1)[1].split("def run", 1)[0]
        self.assertNotIn("manual_announcements", section)
        self.assertNotIn("send_reviewed_batch", section)

    def test_manual_scan_review_loads_pending_queue(self):
        section = self.source.split("def _review_library_announcements", 1)[1].split("def _offer_announcement_baseline", 1)[0]
        self.assertIn("self.db.manual_announcements()", section)
        self.assertIn("announcement_review_required", section)

    def test_review_list_scrolls_while_actions_stay_in_fixed_bottom_frame(self):
        section = self.source.split("def _open_announcement_review", 1)[1].split("def mark_added", 1)[0]
        self.assertIn("Canvas(body", section)
        self.assertIn('Frame(window, name="fixed_review_actions")', section)
        self.assertIn("window.minsize", section)
        self.assertIn("scrollbar.pack(side=RIGHT, fill=Y)", section)

    def test_overlapping_scans_and_duplicate_reviews_are_guarded(self):
        command_section = self.source.split("def start_jellyfin_scan", 1)[1].split("def _configure_tree_copy_actions", 1)[0]
        review_section = self.source.split("def _review_library_announcements", 1)[1].split("def _offer_announcement_baseline", 1)[0]
        threaded_section = self.source.split("def run_threaded", 1)[1].split("def show_message", 1)[0]
        self.assertIn("self._announcement_review_active", command_section)
        self.assertIn("duplicate review was not created", review_section)
        self.assertIn("self._operation_lock.acquire(blocking=False)", threaded_section)
        self.assertIn("self._operation_lock.release()", threaded_section)

    def test_silent_checkbox_persists_without_waiting_for_settings_save(self):
        settings_section = self.source.split("def edit_settings", 1)[1].split("def install_or_update_scheduled_task", 1)[0]
        self.assertIn("command=persist_silent_setting", settings_section)
        self.assertIn("save_shared_silent_setting", settings_section)

    def test_inventory_does_not_insert_anime_records(self):
        inventory_source = (Path(__file__).parents[1] / "src" / "anime_tracker" / "announcements.py").read_text(encoding="utf-8")
        self.assertNotIn("upsert_anime", inventory_source)
        self.assertNotIn("AniList", inventory_source)


if __name__ == "__main__":
    unittest.main()
