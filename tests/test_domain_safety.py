from __future__ import annotations

import ast
import hashlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOMAIN = ROOT / "src" / "anime_tracker" / "domain"
LIVE_DB = ROOT / "data" / "anime_tracker.db"
EXPECTED_LIVE_HASH = "52D2F8D5E1365A655CDB915A6357822EEF21D8D226797A0EE791D03491D4B2A7"


class DomainSafetyTests(unittest.TestCase):
    def test_domain_has_no_gui_network_database_scanner_or_scheduler_imports(self):
        forbidden = {
            "tkinter", "PySide6", "requests", "urllib", "httpx", "discord",
            "sqlite3", "subprocess", "winotify", "scanner", "task_scheduler",
        }
        found: set[str] = set()
        for path in DOMAIN.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    found.update(alias.name.split(".")[0] for alias in node.names if alias.name.split(".")[0] in forbidden)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    root = node.module.split(".")[0]
                    if root in forbidden:
                        found.add(root)
        self.assertEqual(found, set())

    def test_domain_contains_no_file_write_calls(self):
        prohibited = {"open", "write_text", "write_bytes", "unlink", "rename", "rmdir", "mkdir"}
        found: list[str] = []
        for path in DOMAIN.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                    if name in prohibited:
                        found.append(f"{path.name}:{name}")
        self.assertEqual(found, [])

    def test_domain_does_not_name_media_roots_or_storage_checker(self):
        source = "\n".join(path.read_text(encoding="utf-8") for path in DOMAIN.glob("*.py")).casefold()
        self.assertNotIn("jellyfin_media", source)
        self.assertNotIn("storage checker", source)
        self.assertNotIn("set-mkv-english-defaults", source)

    def test_live_database_hash_matches_milestone_checkpoint(self):
        digest = hashlib.sha256(LIVE_DB.read_bytes()).hexdigest().upper()
        self.assertEqual(digest, EXPECTED_LIVE_HASH)


if __name__ == "__main__":
    unittest.main()
