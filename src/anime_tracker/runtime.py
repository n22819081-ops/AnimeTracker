from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "Anime Tracker"
APP_VERSION = "1.0.0"
BUILD_IDENTIFIER = "1.0.0-rc1"
SCHEMA_VERSION = 6
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RELEASE_MANIFEST_NAME = "RELEASE_MANIFEST_1.0.0.json"


def system_drive_root(value: str | None = None) -> Path:
    drive = (value or os.environ.get("SystemDrive") or "C:").rstrip("\\/")
    if drive.endswith(":"):
        drive += "\\"
    return Path(drive).resolve(strict=False)


PROJECT_PRODUCTION_PROFILE = system_drive_root() / "AnimeTracker" / "production_profile"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def application_directory() -> Path:
    return Path(sys.executable).resolve().parent if is_frozen() else PROJECT_ROOT


def per_user_profile_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    return base / APP_NAME / "AnimeTracker"


def default_profile_root() -> Path:
    override = os.environ.get("ANIME_TRACKER_PROFILE", "").strip()
    if override:
        return validate_profile_override(Path(override))
    return per_user_profile_root() if is_frozen() else PROJECT_ROOT / "production_profile"


def validate_profile_override(path: Path) -> Path:
    value = Path(path).expanduser()
    if not value.is_absolute():
        raise ValueError("Profile overrides must use an absolute path.")
    resolved = value.resolve(strict=False)
    if resolved == application_directory().resolve(strict=False):
        raise ValueError("The profile cannot be the application installation directory.")
    protected = {(system_drive_root()/"AnimeTracker"/"data").resolve(strict=False)}
    if resolved in protected:
        raise ValueError("The selected path is not an application-owned profile directory.")
    return resolved


def packaged_resource(*parts: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", application_directory()))
    return root.joinpath(*parts)
