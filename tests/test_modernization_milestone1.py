from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from anime_tracker.modernization.backup import (
    BackupPoint,
    build_manifest,
    plan_backup_retention,
    sha256_file,
    sqlite_integrity_check,
    sqlite_online_backup,
    verify_manifest,
)
from anime_tracker.modernization.inventory import inspect_legacy_database
from anime_tracker.modernization.migration import build_reconciliation, migrate_legacy_copy
from anime_tracker.modernization.redaction import redact_mapping, redact_text
from anime_tracker.modernization.safety import assert_safe_output_path
from anime_tracker.modernization.schema import MODERN_SCHEMA_VERSION, create_modern_database


def create_legacy_fixture(path: Path, *, duplicate_anilist: bool = False) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE anime (
            id INTEGER PRIMARY KEY, english_title TEXT, romaji_title TEXT, native_title TEXT,
            alternate_titles TEXT, anilist_id INTEGER, format TEXT, season TEXT, year INTEGER,
            total_episodes INTEGER, airing_status TEXT, start_date TEXT, expected_end_date TEXT,
            cover_image_url TEXT, anilist_url TEXT, tracker_status TEXT, server_status TEXT,
            detected_server_path TEXT, date_added TEXT, last_checked TEXT, previous_status TEXT,
            notification_state TEXT, manual_notes TEXT, movie_availability TEXT,
            api_failure_count INTEGER, relation_label TEXT, review_reason TEXT
        );
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE notification_events (event_key TEXT PRIMARY KEY, event_type TEXT, anilist_id INTEGER, sent_at TEXT);
        CREATE TABLE server_matches (anilist_id INTEGER PRIMARY KEY, path TEXT, season_label TEXT, confirmation_type TEXT, confirmed_at TEXT);
        CREATE TABLE rejected_matches (anilist_id INTEGER, path TEXT, rejected_at TEXT, normalized_path TEXT, original_path TEXT, PRIMARY KEY(anilist_id,path));
        CREATE TABLE match_candidates (anilist_id INTEGER, path TEXT, confidence TEXT, score INTEGER, reasons TEXT, year INTEGER, media_kind TEXT, scanned_at TEXT, PRIMARY KEY(anilist_id,path));
        CREATE TABLE status_history (id INTEGER PRIMARY KEY, anilist_id INTEGER, event TEXT, previous_status TEXT, new_status TEXT, server_path TEXT, created_at TEXT);
        CREATE TABLE jellyfin_announcement_snapshot (item_type TEXT, normalized_path TEXT PRIMARY KEY, parent_normalized_path TEXT, title TEXT, year INTEGER, season_number INTEGER, original_path TEXT, captured_at TEXT);
        CREATE TABLE manual_announcement_queue (id INTEGER PRIMARY KEY, media_type TEXT, title TEXT, normalized_title TEXT, year INTEGER, season_number INTEGER, episodes_json TEXT, created_at TEXT, updated_at TEXT);
        CREATE TABLE manual_announcement_titles (media_type TEXT, normalized_title TEXT, title TEXT, year INTEGER, last_used_at TEXT, PRIMARY KEY(media_type,normalized_title));
        """
    )
    anime_rows = [
        (1, "Alpha", "Alpha", "", "[]", 1001, "TV", "SPRING", 2025, 12, "FINISHED", "2025-01-01", "2025-03-01", "", "https://anilist.co/anime/1001", "On Server", "On Server", r"I:\Library\Alpha", "2025-01-01", "2026-01-01", "", "", "", "unknown", 0, "Season 1", ""),
        (2, "Alpha Two", "Alpha Two", "", "[]", 1002, "TV", "SPRING", 2026, 12, "RELEASING", "2026-01-01", "", "", "https://anilist.co/anime/1002", "On Server", "On Server", r"I:\Library\Alpha", "2026-01-01", "2026-02-01", "", "", "", "unknown", 0, "Season 2", ""),
    ]
    if duplicate_anilist:
        anime_rows.append((3, "Duplicate", "Duplicate", "", "[]", 1001, "TV", "", 2025, 1, "FINISHED", "", "", "", "", "Finished / Ready to Add", "Not Found", "", "2025-01-01", "", "", "", "", "unknown", 0, "", ""))
    connection.executemany("INSERT INTO anime VALUES(" + ",".join("?" for _ in range(27)) + ")", anime_rows)
    connection.executemany(
        "INSERT INTO server_matches VALUES(?,?,?,?,?)",
        [
            (1001, r"I:\Library\Alpha", "Season 1", "manual", "2026-01-01"),
            (1002, r"I:\Library\Alpha", "Season 2", "manual", "2026-01-01"),
            (9999, r"I:\Library\Removed", "", "automatic", "2025-01-01"),
        ],
    )
    connection.executemany(
        "INSERT INTO rejected_matches VALUES(?,?,?,?,?)",
        [
            (1001, r"i:\wrong", "2026-01-01", r"i:\wrong", r"I:\Wrong"),
            (9999, r"i:\old", "2025-01-01", r"i:\old", r"I:\Old"),
        ],
    )
    connection.executemany(
        "INSERT INTO match_candidates VALUES(?,?,?,?,?,?,?,?)",
        [
            (1002, r"I:\Library\Alpha", "possible", 80, "[]", 2025, "TV", "2026-01-01"),
            (9999, r"I:\Library\Removed", "possible", 60, "[]", 2020, "TV", "2025-01-01"),
        ],
    )
    connection.executemany(
        "INSERT INTO status_history VALUES(?,?,?,?,?,?,?)",
        [
            (1, 1001, "Confirmed", "Ready", "On Server", r"I:\Library\Alpha", "2026-01-01"),
            (2, 9999, "Removed legacy record", "On Server", "", r"I:\Library\Removed", "2025-01-01"),
        ],
    )
    connection.execute("INSERT INTO notification_events VALUES('status:1001','status',1001,'2026-01-01')")
    connection.execute("INSERT INTO jellyfin_announcement_snapshot VALUES('TV_SHOW','i:\\library\\alpha','','Alpha',2025,NULL,'I:\\Library\\Alpha','2026-01-01')")
    connection.execute("INSERT INTO manual_announcement_queue VALUES(1,'TV_SHOW','Alpha','alpha',2025,1,'[1]','2026-01-01','2026-01-01')")
    connection.execute("INSERT INTO manual_announcement_titles VALUES('TV_SHOW','alpha','Alpha',2025,'2026-01-01')")
    connection.executemany("INSERT INTO settings VALUES(?,?)", [("theme", "Dark"), ("schedule_frequency", "Weekly")])
    connection.commit()
    connection.close()


class BackupTests(unittest.TestCase):
    def test_backup_manifest_generation_and_sha256_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root / "value.txt"
            file.write_text("preserve me", encoding="utf-8")
            manifest = build_manifest(root, [file])
            self.assertEqual(manifest["files"][0]["sha256"], sha256_file(file))
            self.assertEqual(verify_manifest(root, manifest), [])
            file.write_text("changed", encoding="utf-8")
            self.assertEqual(verify_manifest(root, manifest), ["size:value.txt"])

    def test_sqlite_online_backup_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, destination = root / "source.db", root / "backup.db"
            connection = sqlite3.connect(source)
            connection.execute("CREATE TABLE value(id INTEGER PRIMARY KEY)")
            connection.execute("INSERT INTO value VALUES(1)")
            connection.commit()
            connection.close()
            sqlite_online_backup(source, destination)
            self.assertEqual(sqlite_integrity_check(destination), "ok")
            backup_connection = sqlite3.connect(destination)
            try:
                self.assertEqual(backup_connection.execute("SELECT COUNT(*) FROM value").fetchone()[0], 1)
            finally:
                backup_connection.close()

    def test_retention_planner_does_not_delete_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            now = datetime(2026, 8, 1, tzinfo=timezone.utc)
            points = []
            for day in range(20):
                path = root / f"backup-{day}.db"
                path.write_text(str(day), encoding="ascii")
                points.append(BackupPoint(path, now - timedelta(days=day)))
            plan = plan_backup_retention(points, now)
            self.assertTrue(plan["keep"])
            self.assertEqual(len(list(root.iterdir())), 20)


class SchemaAndMigrationTests(unittest.TestCase):
    def run_migration(self, root: Path, *, duplicate: bool = False):
        live = root / "live.db"
        backup = root / "legacy-backup.db"
        destination = root / "modern.db"
        create_legacy_fixture(live, duplicate_anilist=duplicate)
        sqlite_online_backup(live, backup)
        live_hash = sha256_file(live)
        result = migrate_legacy_copy(
            backup,
            destination,
            live_database_path=live,
            protected_roots=(root / "protected-media",),
            storage_checker_path=root / "storage-checker",
        )
        self.assertEqual(sha256_file(live), live_hash)
        return live, backup, destination, result

    def test_new_database_starts_empty_and_tracks_schema_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "modern.db"
            create_modern_database(path, protected_roots=())
            connection = sqlite3.connect(path)
            self.assertEqual(connection.execute("SELECT version FROM schema_migrations").fetchone()[0], MODERN_SCHEMA_VERSION)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM tracked_media").fetchone()[0], 0)
            connection.close()

    def test_row_inventory_and_orphans_are_preserved_without_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _live, backup, destination, result = self.run_migration(root)
            inventory = inspect_legacy_database(backup)
            self.assertEqual(inventory["orphan_counts"]["server_matches"], 1)
            report = build_reconciliation(backup, destination, result)
            self.assertEqual(report["unexplained_loss_tables"], [])
            self.assertEqual(report["unresolved_archived_records"], 4)
            connection = sqlite3.connect(destination)
            reasons = [row[0] for row in connection.execute("SELECT reason FROM archived_legacy_records")]
            connection.close()
            self.assertTrue(all("Manual review required" in reason for reason in reasons))

    def test_duplicate_anilist_id_is_archived(self):
        with tempfile.TemporaryDirectory() as tmp:
            _live, _backup, destination, result = self.run_migration(Path(tmp), duplicate=True)
            self.assertEqual(result["audit"]["anime"]["active"], 2)
            self.assertEqual(result["audit"]["anime"]["archived"], 1)
            connection = sqlite3.connect(destination)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM archived_legacy_records WHERE source_table='anime'").fetchone()[0], 1)
            connection.close()

    def test_shared_jellyfin_path_and_multiple_anilist_mappings_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            _live, _backup, destination, _result = self.run_migration(Path(tmp))
            connection = sqlite3.connect(destination)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM server_library_items").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM media_server_mappings").fetchone()[0], 2)
            connection.close()

    def test_legacy_status_mapping_keeps_coverage_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            _live, _backup, destination, _result = self.run_migration(Path(tmp))
            connection = sqlite3.connect(destination)
            rows = connection.execute("SELECT tracker_status,server_presence,episode_coverage FROM tracking_state").fetchall()
            connection.close()
            self.assertTrue(all(row[0] == "On Server" for row in rows))
            self.assertTrue(all(row[1:] == ("UNKNOWN_COVERAGE", "UNKNOWN") for row in rows))

    def test_prototype_refuses_live_database_as_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = root / "live.db"
            create_legacy_fixture(live)
            with self.assertRaises(ValueError):
                migrate_legacy_copy(live, root / "modern.db", live_database_path=live, protected_roots=())

    def test_protected_media_and_storage_checker_outputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            media = root / "media"
            checker = root / "storage-checker"
            media.mkdir()
            checker.mkdir()
            with self.assertRaises(ValueError):
                assert_safe_output_path(media / "write.db", protected_roots=(media,))
            before = list(checker.iterdir())
            with self.assertRaises(ValueError):
                assert_safe_output_path(checker / "write.db", protected_roots=(), storage_checker_path=checker)
            self.assertEqual(list(checker.iterdir()), before)


class RedactionAndIgnoreTests(unittest.TestCase):
    def test_secret_redaction(self):
        webhook = "https://discord.com/api/webhooks/123/secret-value"
        self.assertNotIn("secret-value", redact_text(webhook))
        result = redact_mapping({"discord_webhook_url": webhook, "message": webhook})
        self.assertEqual(result["discord_webhook_url"], "<redacted>")
        self.assertNotIn("secret-value", json.dumps(result))

    def test_migration_result_excludes_webhook_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = root / "live.db"
            backup = root / "backup.db"
            create_legacy_fixture(live)
            connection = sqlite3.connect(live)
            connection.execute("INSERT INTO settings VALUES('discord_webhook_url','https://discord.com/api/webhooks/123/private')")
            connection.commit()
            connection.close()
            sqlite_online_backup(live, backup)
            result = migrate_legacy_copy(backup, root / "modern.db", live_database_path=live, protected_roots=())
            self.assertNotIn("/123/private", json.dumps(result))

    def test_gitignore_excludes_live_data_secrets_and_generated_content(self):
        source = (Path(__file__).parents[1] / ".gitignore").read_text(encoding="utf-8")
        for required in ("data/", "logs/", "backups/", "modernization_backups/", ".venv/", ".pytest_cache/", "*.py[cod]", "migration_test/", "*.lock", "jellyfin storage checker/"):
            self.assertIn(required, source)


if __name__ == "__main__":
    unittest.main()
