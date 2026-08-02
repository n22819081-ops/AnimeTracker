from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PRODUCTION_PROFILE = ROOT / "production_profile"
LIVE_LEGACY_DATABASE = ROOT / "data" / "anime_tracker.db"


def default_bootstrap() -> dict:
    return {
        "profile_type": "production",
        "migration_state": "NOT_STARTED",
        "cutover_state": "PENDING_APPROVAL",
        "notifications_stage": 1,
        "private_notifications_enabled": False,
        "shared_notifications_enabled": False,
        "weekly_summaries_enabled": False,
        "anilist_refresh_enabled": False,
        "jellyfin_scan_enabled": False,
        "scheduled_checks_enabled": False,
        "legacy_task_disabled": False,
        "credential_migration_state": "PENDING_APPROVAL",
        "initial_baseline_accepted": False,
        "notification_baseline_state": "MIGRATED_PREVIEW_PENDING",
        "initial_events_created": 0,
        "migration_version": "0.8.0",
    }


@dataclass(frozen=True)
class ProductionProfile:
    root: Path = DEFAULT_PRODUCTION_PROFILE

    @property
    def data_dir(self) -> Path: return self.root / "data"
    @property
    def database_path(self) -> Path: return self.data_dir / "anime_tracker_modern.db"
    @property
    def logs_dir(self) -> Path: return self.root / "logs"
    @property
    def backups_dir(self) -> Path: return self.root / "backups"
    @property
    def cache_dir(self) -> Path: return self.root / "cache"
    @property
    def diagnostics_dir(self) -> Path: return self.root / "diagnostics"
    @property
    def locks_dir(self) -> Path: return self.root / "execution" / "locks"
    @property
    def bootstrap_path(self) -> Path: return self.root / "bootstrap.json"
    @property
    def settings_path(self) -> Path: return self.root / "settings.json"
    @property
    def credentials_dir(self) -> Path: return self.data_dir / "credentials"

    def initialize_directories(self) -> None:
        if self.database_path.resolve() == LIVE_LEGACY_DATABASE.resolve():
            raise ValueError("The modern production profile cannot use the legacy database.")
        for path in (
            self.data_dir, self.logs_dir, self.backups_dir, self.cache_dir / "anilist",
            self.cache_dir / "covers", self.diagnostics_dir, self.locks_dir, self.credentials_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        if not self.bootstrap_path.exists(): self.save_bootstrap(default_bootstrap())
        if not self.settings_path.exists(): self.save_settings({"theme": "Dark", "test_tv_path": "", "test_movie_path": ""})

    def load_bootstrap(self) -> dict:
        value = json.loads(self.bootstrap_path.read_text(encoding="utf-8")) if self.bootstrap_path.exists() else {}
        return {**default_bootstrap(), **value}

    def save_bootstrap(self, value: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.bootstrap_path.write_text(json.dumps(_without_secrets(value), indent=2, sort_keys=True), encoding="utf-8")

    def load_settings(self) -> dict:
        if not self.settings_path.exists(): return {"theme": "Dark"}
        return json.loads(self.settings_path.read_text(encoding="utf-8"))

    def save_settings(self, value: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps(_without_secrets(value), indent=2, sort_keys=True), encoding="utf-8")

    def assert_reset_allowed(self, *, confirmation: str, verified_backup: Path | None) -> None:
        if confirmation != "RESET MODERN PRODUCTION PROFILE":
            raise PermissionError("Production reset requires the exact confirmation phrase.")
        if verified_backup is None or not verified_backup.is_dir() or not (verified_backup / "manifest.json").is_file():
            raise PermissionError("Production reset requires a verified backup directory.")


def _without_secrets(value: dict) -> dict:
    forbidden = ("webhook", "secret", "token", "password", "api_key")
    return {key: item for key, item in value.items() if not any(word in key.casefold() for word in forbidden)}
