from __future__ import annotations

import hashlib
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from anime_tracker.domain.enums import LibraryKind
from anime_tracker.domain.legacy_adapter import adapt_legacy_anime_row
from anime_tracker.services.server_inventory import FilesystemInventoryService, LibraryRoot


ROOT = Path(__file__).resolve().parents[1]
BACKUP_DB = ROOT / "Modern Anime Tracker" / "modernization_backups" / "20260801-230906-verified" / "sqlite_online" / "anime_tracker.db"


class ServerInventoryCompatibilityTests(unittest.TestCase):
    @unittest.skipUnless(BACKUP_DB.exists(), "verified Milestone 1 backup is not present")
    def test_all_69_active_records_remain_representable_with_temporary_inventory(self):
        source_hash = hashlib.sha256(BACKUP_DB.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database_copy = root / "legacy-copy.db"
            shutil.copy2(BACKUP_DB, database_copy)
            connection = sqlite3.connect(database_copy)
            connection.row_factory = sqlite3.Row
            try:
                rows = list(connection.execute("SELECT * FROM anime ORDER BY id"))
                before = tuple(adapt_legacy_anime_row(row) for row in rows)
            finally:
                connection.close()

            media_root = root / "media"
            episode = media_root / "Compatibility Fixture" / "Season 02" / "Fixture.S02E01.mkv"
            episode.parent.mkdir(parents=True)
            episode.touch()
            snapshot = FilesystemInventoryService().scan((
                LibraryRoot("Compatibility", str(media_root), LibraryKind.TV),
            ))

            connection = sqlite3.connect(database_copy)
            connection.row_factory = sqlite3.Row
            try:
                after_rows = list(connection.execute("SELECT * FROM anime ORDER BY id"))
                after = tuple(adapt_legacy_anime_row(row) for row in after_rows)
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(len(before), 69)
        self.assertEqual(before, after)
        self.assertEqual(integrity, "ok")
        self.assertEqual(snapshot.items[0].seasons[0].season_number, 2)
        self.assertEqual(hashlib.sha256(BACKUP_DB.read_bytes()).hexdigest(), source_hash)


if __name__ == "__main__":
    unittest.main()
