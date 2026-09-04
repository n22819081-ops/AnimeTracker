from __future__ import annotations

import ast
import hashlib
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from anime_tracker.modernization.schema_v4 import migrate_modern_database_to_v4


ROOT = Path(__file__).resolve().parents[1]
MATCHING = ROOT / "src" / "anime_tracker" / "services" / "matching"
V3_PROTOTYPE = ROOT / "Modern Anime Tracker" / "migration_test" / "anime_tracker_modern_v3.db"
LIVE_DB = ROOT / "Legacy Anime Tracker" / "data" / "anime_tracker.db"
EXPECTED_LIVE_HASH = "0CBA84F7D08EAD16A69C1DF49D0A79A8351940A4D28E8049C60E591A1176BEB8"


class MatchingSafetyTests(unittest.TestCase):
    def test_matching_layer_has_no_gui_network_notifications_scheduler_or_external_tools(self):
        forbidden_imports = {
            "requests", "subprocess", "tkinter", "winotify", "webbrowser",
        }
        found = set()
        source = []
        for path in MATCHING.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            source.append(text.casefold())
            tree = ast.parse(text, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    found.update(alias.name.split(".")[0] for alias in node.names if alias.name.split(".")[0] in forbidden_imports)
                elif isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in forbidden_imports:
                    found.add(node.module.split(".")[0])
        self.assertEqual(found, set())
        joined = "\n".join(source)
        for forbidden in (
            "discord.com/api/webhooks", "jellyfin_media", "storage checker", "sonarr", "radarr",
            "register-scheduledtask", "set-mkv-english-defaults",
        ):
            self.assertNotIn(forbidden, joined)

    def test_matching_layer_contains_no_media_file_write_move_or_delete_calls(self):
        prohibited = {
            "chmod", "copy", "copy2", "mkdir", "move", "remove", "rename",
            "rmdir", "touch", "unlink", "write_bytes", "write_text",
        }
        found = []
        for path in MATCHING.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
                    if name in prohibited:
                        found.append(f"{path.name}:{name}")
        self.assertEqual(found, [])

    def test_repository_stores_only_database_path_not_connection(self):
        source = (MATCHING / "repository.py").read_text(encoding="utf-8")
        self.assertIn("self.database_path", source)
        self.assertNotIn("self.connection", source)
        self.assertIn("finally:\n            connection.close()", source)

    def test_live_database_hash_remains_milestone_checkpoint(self):
        self.assertEqual(hashlib.sha256(LIVE_DB.read_bytes()).hexdigest().upper(), EXPECTED_LIVE_HASH)


class MatchingLegacyV4Tests(unittest.TestCase):
    @unittest.skipUnless(V3_PROTOTYPE.exists(), "schema-v3 prototype is unavailable")
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.copy = Path(self.temp.name) / "modern-v4.db"
        shutil.copy2(V3_PROTOTYPE, self.copy)
        migrate_modern_database_to_v4(self.copy, live_database_path=LIVE_DB, protected_roots=())
        self.connection = sqlite3.connect(self.copy)
        self.connection.row_factory = sqlite3.Row

    def tearDown(self):
        if hasattr(self, "connection"):
            self.connection.close()
        if hasattr(self, "temp"):
            self.temp.cleanup()

    def test_active_legacy_mapping_is_confirmed_without_invented_season(self):
        row = self.connection.execute("SELECT * FROM media_server_mappings").fetchone()
        self.assertEqual(row["mapping_source"], "LEGACY_IMPORT")
        self.assertEqual(row["confirmation_state"], "CONFIRMED")
        self.assertIsNone(row["season_number"])
        self.assertEqual(row["target_type"], "UNKNOWN_TARGET")

    def test_legacy_path_rejections_remain_exact_path_rejections(self):
        rows = self.connection.execute("SELECT scope FROM rejected_match_decisions").fetchall()
        self.assertTrue(rows)
        self.assertEqual({row["scope"] for row in rows}, {"EXACT_PATH"})

    def test_legacy_candidates_are_historical_stale_evidence(self):
        rows = self.connection.execute("SELECT stale,confidence,evidence_json FROM server_match_candidates").fetchall()
        self.assertEqual(len(rows), 14)
        self.assertTrue(all(row["stale"] == 1 for row in rows))
        self.assertTrue(all(row["confidence"] == "INSUFFICIENT_EVIDENCE" for row in rows))
        self.assertTrue(all("Legacy score" in row["evidence_json"] for row in rows))

    def test_normal_legacy_no_match_reviews_remain_audited_not_active(self):
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM legacy_review_cases_v1 WHERE reason='No Jellyfin match found'"
        ).fetchone()[0], 59)
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM review_cases WHERE evidence_json LIKE '%No Jellyfin match found%'"
        ).fetchone()[0], 0)

    def test_orphans_and_manual_on_server_evidence_remain_preserved(self):
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM archived_legacy_records").fetchone()[0], 421)
        mapping = self.connection.execute("SELECT COUNT(*) FROM media_server_mappings").fetchone()[0]
        self.assertEqual(mapping, 1)
        payload = self.connection.execute(
            "SELECT legacy_payload_json FROM tracked_media WHERE anilist_id=(SELECT anilist_id FROM media_server_mappings LIMIT 1)"
        ).fetchone()[0]
        self.assertIn("On Server", payload)

    def test_original_v1_matching_tables_remain_as_audit_tables(self):
        for table in (
            "legacy_media_server_mappings_v1", "legacy_rejected_match_decisions_v1",
            "legacy_match_candidates_v1", "legacy_review_cases_v1",
        ):
            self.assertIsNotNone(self.connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone())


if __name__ == "__main__":
    unittest.main()
