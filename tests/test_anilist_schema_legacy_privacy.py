from __future__ import annotations

import ast
import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from anime_tracker.modernization.schema_v3 import migrate_modern_database_to_v3
from anime_tracker.services.anilist.client import AniListGraphQLClient
from anime_tracker.services.anilist.legacy_adapter import compare_legacy_values, modern_media_to_legacy_values, unresolved_legacy_relation
from anime_tracker.services.anilist.live_check import run_optional_live_check
from anime_tracker.services.anilist.models import parse_media
from anime_tracker.services.anilist.queries import MEDIA_BY_ID_QUERY

from anilist_helpers import FIXTURE_ROOT, NOW, FakeResponse, client_for, fixture, media_response

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "migration_test" / "anime_tracker_modern_v1.db"
BACKUP_DB = ROOT / "modernization_backups" / "20260801-230906-verified" / "sqlite_online" / "anime_tracker.db"
LIVE_DB = ROOT / "data" / "anime_tracker.db"
EXPECTED_LIVE_HASH = "69763FC9EC883096041C6EDEDD9399B4697EBC650A48D07BA87879C787B3782E"


class SchemaV3Tests(unittest.TestCase):
    @unittest.skipUnless(PROTOTYPE.exists(), "Milestone 1 prototype is unavailable")
    def test_v1_copy_migrates_transactionally_to_v3_without_row_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "modern-v3.db"
            shutil.copy2(PROTOTYPE, copy)
            connection = sqlite3.connect(copy)
            before = {table: connection.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0] for table in ("tracked_media", "archived_legacy_records", "media_server_mappings", "status_history")}
            connection.close()
            migrate_modern_database_to_v3(copy, live_database_path=LIVE_DB, protected_roots=())
            connection = sqlite3.connect(copy)
            try:
                versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
                after = {table: connection.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0] for table in before}
                self.assertEqual(versions, [1, 2, 3])
                self.assertEqual(after, before)
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
                for table in ("anilist_media_cache", "anilist_title_variants", "anilist_relations", "anilist_airing_schedule", "anilist_refresh_items", "anilist_request_state", "franchise_graph_nodes", "franchise_graph_edges"):
                    self.assertIsNotNone(connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone())
            finally:
                connection.close()

    @unittest.skipUnless(PROTOTYPE.exists(), "Milestone 1 prototype is unavailable")
    def test_v3_migration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "modern-v3.db"
            shutil.copy2(PROTOTYPE, copy)
            migrate_modern_database_to_v3(copy, live_database_path=LIVE_DB, protected_roots=())
            migrate_modern_database_to_v3(copy, live_database_path=LIVE_DB, protected_roots=())
            connection = sqlite3.connect(copy)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM schema_migrations WHERE version IN (2,3)").fetchone()[0], 2)
            finally:
                connection.close()

    def test_live_database_migration_is_refused(self):
        with self.assertRaises(ValueError):
            migrate_modern_database_to_v3(LIVE_DB, live_database_path=LIVE_DB, protected_roots=())


class LegacyCompatibilityTests(unittest.TestCase):
    def test_modern_values_convert_to_legacy_shape(self):
        media = parse_media(fixture("media_cases.json")["airing_tv"], NOW)
        values = modern_media_to_legacy_values(media)
        self.assertEqual((values["anilist_id"], values["airing_status"], values["format"]), (1002, "RELEASING", "TV"))

    def test_generic_legacy_relation_is_preserved_unresolved(self):
        relation = unresolved_legacy_relation({"anilist_id": 1002, "relation_label": "Season 2"}, NOW)
        self.assertIsNone(relation.target_anilist_id)
        self.assertEqual(relation.legacy_label, "Season 2")
        self.assertFalse(relation.provider_confirmed)

    @unittest.skipUnless(BACKUP_DB.exists(), "Verified backup is unavailable")
    def test_all_69_active_records_accept_modern_typed_metadata(self):
        connection = sqlite3.connect(f"file:{BACKUP_DB.as_posix()}?mode=ro&immutable=1", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            rows = list(connection.execute("SELECT * FROM anime ORDER BY id"))
        finally:
            connection.close()
        represented = []
        for row in rows:
            payload = {
                "id": row["anilist_id"],
                "title": {"english": row["english_title"], "romaji": row["romaji_title"], "native": row["native_title"]},
                "synonyms": json.loads(row["alternate_titles"] or "[]"),
                "format": row["format"], "status": row["airing_status"], "season": row["season"],
                "seasonYear": row["year"], "episodes": row["total_episodes"],
                "siteUrl": row["anilist_url"], "relations": {"edges": []},
            }
            media = parse_media(payload, NOW)
            represented.append(modern_media_to_legacy_values(media))
        self.assertEqual(len(represented), 69)
        self.assertEqual(len({item["anilist_id"] for item in represented}), 69)


class PrivacyAndSafetyTests(unittest.TestCase):
    def test_request_body_contains_no_local_or_secret_data(self):
        media = fixture("media_cases.json")["upcoming_tv"]
        client, session = client_for([media_response(media)])
        client.execute(MEDIA_BY_ID_QUERY, {"id": 1001})
        body = json.dumps(session.calls[0][1]["json"])
        for forbidden in ("I:\\", "Jellyfin", "webhook", "Drtal", "COMPUTERNAME", "USERNAME"):
            self.assertNotIn(forbidden.casefold(), body.casefold())

    def test_logs_do_not_expose_graphql_variables_or_raw_errors(self):
        client, _ = client_for([FakeResponse(200, {"errors": [{"message": "Variable provider-detail invalid"}]})])
        with self.assertLogs("anime_tracker.services.anilist.client", level="WARNING") as logs:
            with self.assertRaises(Exception):
                client.execute(MEDIA_BY_ID_QUERY, {"search": "do-not-log"})
        output = " ".join(logs.output)
        self.assertNotIn("do-not-log", output)
        self.assertNotIn("provider-detail", output)

    def test_sanitized_fixtures_contain_no_local_paths_or_secrets(self):
        source = "\n".join(path.read_text(encoding="utf-8") for path in FIXTURE_ROOT.glob("*.json")).casefold()
        for forbidden in ("i:\\jellyfin", "discord.com/api/webhooks", "drtal", "computername", "password", "api_key"):
            self.assertNotIn(forbidden, source)

    def test_service_layer_has_no_gui_discord_jellyfin_or_scheduler_dependencies(self):
        service_root = ROOT / "src" / "anime_tracker" / "services" / "anilist"
        forbidden = {"tkinter", "PySide6", "discord", "scanner", "task_scheduler", "subprocess", "winotify"}
        found = set()
        source = []
        for path in service_root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            source.append(text.casefold())
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    found.update(alias.name.split(".")[0] for alias in node.names if alias.name.split(".")[0] in forbidden)
                elif isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in forbidden:
                    found.add(node.module.split(".")[0])
        self.assertEqual(found, set())
        joined = "\n".join(source)
        self.assertNotIn("jellyfin_media", joined)
        self.assertNotIn("storage checker", joined)

    def test_live_database_hash_is_unchanged(self):
        self.assertEqual(hashlib.sha256(LIVE_DB.read_bytes()).hexdigest().upper(), EXPECTED_LIVE_HASH)

    def test_optional_live_check_is_disabled_by_default(self):
        with patch.dict("os.environ", {"ANIME_TRACKER_ANILIST_LIVE_CHECK": "0"}):
            result = run_optional_live_check()
        self.assertFalse(result.ran)
        self.assertEqual(result.requested_ids, ())


if __name__ == "__main__":
    unittest.main()
