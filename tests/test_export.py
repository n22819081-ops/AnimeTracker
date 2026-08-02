import tempfile
import unittest
from pathlib import Path

from anime_tracker.database import Database
from anime_tracker.models import AnimeRecord


class ExportTests(unittest.TestCase):
    def test_export_csv_writes_tracker_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = Database(root / "tracker.db")
            db.upsert_anime(
                AnimeRecord(
                    english_title="Export Title",
                    romaji_title="Export Romaji",
                    native_title="",
                    alternate_titles=[],
                    anilist_id=555,
                    format="TV",
                    season="SUMMER",
                    year=2026,
                    total_episodes=12,
                    airing_status="RELEASING",
                    start_date="2026-07-01",
                    expected_end_date="2026-09-30",
                    cover_image_url="",
                    anilist_url="https://anilist.co/anime/555",
                    tracker_status="Currently Airing",
                )
            )
            output = root / "tracker.csv"

            db.export_csv(output)

            text = output.read_text(encoding="utf-8")
            self.assertIn("english_title", text)
            self.assertIn("Export Title", text)
            self.assertIn("555", text)


if __name__ == "__main__":
    unittest.main()
