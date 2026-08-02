from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
LIVE_DATABASE = ROOT / "data" / "anime_tracker.db"
DEFAULT_PROFILE = ROOT / "modern_profile_test"
PROTOTYPE_DATABASE = ROOT / "migration_test" / "anime_tracker_modern_v5.db"


@dataclass(frozen=True)
class ModernProfile:
    root: Path

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "anime_tracker_modern.db"

    @property
    def settings_path(self) -> Path:
        return self.root / "settings.json"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    def initialize(self, *, prototype: Path = PROTOTYPE_DATABASE) -> None:
        if self.database_path.resolve() == LIVE_DATABASE.resolve():
            raise ValueError("Modern GUI refuses the live legacy database.")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if not self.database_path.exists():
            if not prototype.exists():
                raise FileNotFoundError("The schema-v5 migration-test prototype is unavailable.")
            shutil.copy2(prototype, self.database_path)
        if not self.settings_path.exists():
            self.save_settings(default_settings())

    def load_settings(self) -> dict:
        try:
            value = json.loads(self.settings_path.read_text(encoding="utf-8"))
            return {**default_settings(), **value}
        except (OSError, ValueError, TypeError):
            return {**default_settings(), "settings_recovered": True}

    def save_settings(self, settings: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        safe = {key: value for key, value in settings.items() if "webhook" not in key.casefold() and "secret" not in key.casefold()}
        self.settings_path.write_text(json.dumps(safe, indent=2, sort_keys=True), encoding="utf-8")

    def reset(self, *, prototype: Path = PROTOTYPE_DATABASE) -> None:
        if self.database_path.exists():
            self.database_path.unlink()
        if self.settings_path.exists():
            self.settings_path.unlink()
        self.initialize(prototype=prototype)


def default_settings() -> dict:
    return {
        "theme": "Dark",
        "last_page": "Dashboard",
        "window_geometry": "",
        "table_columns": {},
        "test_tv_path": "",
        "test_movie_path": "",
        "notifications_private_enabled": False,
        "notifications_shared_enabled": False,
        "notifications_windows_enabled": False,
        "automatic_anilist_refresh": False,
        "automatic_inventory_scan": False,
    }
