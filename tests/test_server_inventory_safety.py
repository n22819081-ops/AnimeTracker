from __future__ import annotations

import ast
import unittest
from pathlib import Path

from anime_tracker.modernization.safety import DEFAULT_PROTECTED_ROOTS


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PACKAGE = ROOT / "src" / "anime_tracker" / "services" / "server_inventory"


class ServerInventorySafetyTests(unittest.TestCase):
    def test_all_three_media_roots_are_protected_outputs(self):
        values = {str(path) for path in DEFAULT_PROTECTED_ROOTS}
        self.assertEqual(values, {
            r"I:\Jellyfin_Media\TV-SHOWs",
            r"I:\Jellyfin_Media\Movies",
            r"I:\Jellyfin_Media\Anime",
        })

    def test_inventory_has_no_write_delete_move_network_database_or_subprocess_calls(self):
        prohibited_calls = {
            "chmod", "mkdir", "open", "remove", "rename", "replace", "rmdir", "unlink",
            "write", "write_bytes", "write_text",
        }
        prohibited_imports = {
            "requests", "sqlite3", "subprocess", "tkinter", "winotify",
        }
        calls = []
        imports = []
        for path in INVENTORY_PACKAGE.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
                    if name in prohibited_calls:
                        calls.append(f"{path.name}:{name}")
                elif isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names if alias.name.split(".")[0] in prohibited_imports)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.split(".")[0] in prohibited_imports:
                        imports.append(node.module)
        self.assertEqual(calls, [])
        self.assertEqual(imports, [])

    def test_inventory_does_not_depend_on_gui_notifications_scheduler_or_matching(self):
        source = "\n".join(path.read_text(encoding="utf-8") for path in INVENTORY_PACKAGE.glob("*.py")).casefold()
        for forbidden in (
            "anime_tracker.app", "from ...app", "announcement", "discord", "notification",
            "scheduler", "match_record",
        ):
            self.assertNotIn(forbidden, source)

    def test_inventory_source_contains_no_anilist_identity_inference(self):
        source = "\n".join(path.read_text(encoding="utf-8") for path in INVENTORY_PACKAGE.glob("*.py")).casefold()
        self.assertNotIn("anilist_id", source)
        self.assertNotIn("digital_availability", source)


if __name__ == "__main__":
    unittest.main()
