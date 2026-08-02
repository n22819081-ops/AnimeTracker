from __future__ import annotations

import json
import shutil
from pathlib import Path

from anime_tracker.modernization.backup import build_manifest
from anime_tracker.production.profile import ProductionProfile
from anime_tracker.production.schema import migrate_to_production_schema


ROOT=Path(__file__).resolve().parents[1]
V5=ROOT/"migration_test"/"anime_tracker_modern_v5.db"
LEGACY=ROOT/"migration_test"/"legacy_gui_verification.db"


def production_profile(tmp_path:Path)->ProductionProfile:
    profile=ProductionProfile(tmp_path/"production");profile.initialize_directories();shutil.copy2(V5,profile.database_path);migrate_to_production_schema(profile.database_path);return profile


def verified_legacy_backup(tmp_path:Path)->Path:
    folder=tmp_path/"verified-backup";folder.mkdir();shutil.copy2(LEGACY,folder/"anime_tracker-online.db");manifest=build_manifest(folder,[folder/"anime_tracker-online.db"]);(folder/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8");return folder
