import unittest

from anime_tracker.tree_copy import (
    COPY_ANILIST_ID,
    COPY_ENGLISH_TITLE,
    COPY_ROMAJI_TITLE,
    COPY_SELECTED_ROW,
    copy_value,
    default_copy_value,
    row_to_select,
)


class TreeCopyTests(unittest.TestCase):
    def setUp(self):
        self.row = {
            "english_title": "Full Title",
            "romaji_title": "Romaji Title",
            "anilist_id": 12345,
            "season": "SPRING",
            "year": 2026,
            "format": "TV",
            "airing_status": "RELEASING",
            "tracker_status": "Currently Airing",
            "server_status": "Not Found",
            "detected_server_path": "",
        }

    def test_copy_individual_values(self):
        self.assertEqual(copy_value(self.row, COPY_ENGLISH_TITLE), "Full Title")
        self.assertEqual(copy_value(self.row, COPY_ROMAJI_TITLE), "Romaji Title")
        self.assertEqual(copy_value(self.row, COPY_ANILIST_ID), "12345")

    def test_copy_selected_row_is_tab_separated(self):
        value = copy_value(self.row, COPY_SELECTED_ROW)
        self.assertIn("Full Title\tRomaji Title\t12345", value)

    def test_ctrl_c_prefers_english_then_romaji(self):
        self.assertEqual(default_copy_value(self.row), "Full Title")
        self.assertEqual(default_copy_value({"english_title": "", "romaji_title": "Fallback"}), "Fallback")

    def test_right_click_selects_identified_row(self):
        self.assertEqual(row_to_select("42"), "42")
        self.assertIsNone(row_to_select(""))


if __name__ == "__main__":
    unittest.main()
