"""Milestone 8 production-layer performance benchmark."""
from __future__ import annotations

import json
import shutil
import tempfile
import time
from pathlib import Path

from anime_tracker.gui_qt.data import ModernRepository
from anime_tracker.production.backup_restore import ModernBackupManager,ModernRestoreManager
from anime_tracker.production.comparison import build_legacy_modern_comparison
from anime_tracker.production.diagnostics import DiagnosticsReporter
from anime_tracker.production.migration import ProductionMigrator
from anime_tracker.production.profile import ProductionProfile
from anime_tracker.production.schema import migrate_to_production_schema
from anime_tracker.services.anilist.cache import AniListCache
from production_helpers import LEGACY,V5,verified_legacy_backup


def timed(callable_value):
    started=time.perf_counter();value=callable_value();return (time.perf_counter()-started)*1000,value


def main():
    values={}
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);backup=verified_legacy_backup(root);migration_profile=ProductionProfile(root/"migration")
        values["database_migration_ms"],migration=timed(lambda:ProductionMigrator(migration_profile,live_database=LEGACY).migrate_from_verified_backup(backup))
        profile=ProductionProfile(root/"operations");profile.initialize_directories();shutil.copy2(V5,profile.database_path);migrate_to_production_schema(profile.database_path)
        values["production_profile_startup_69_ms"],repository=timed(lambda:ModernRepository(profile.database_path))
        values["cached_69_row_load_ms"],rows=timed(lambda:repository.tracked_media())
        cache=AniListCache(profile.database_path);ids=tuple(row.anilist_id for row in rows)
        values["cached_anilist_69_load_ms"],_=timed(lambda:cache.get_many_media(ids,__import__("datetime").datetime.now(__import__("datetime").timezone.utc)))
        values["legacy_modern_comparison_ms"],_=timed(lambda:build_legacy_modern_comparison(LEGACY,profile.database_path))
        values["status_recalculation_69_ms"],_=timed(lambda:tuple((row.anilist_status,row.tracker_status,row.server_status,row.coverage) for row in repository.tracked_media()))
        values["dashboard_population_ms"],_=timed(repository.dashboard_counts)
        manager=ModernBackupManager(profile);values["backup_ms"],modern_backup=timed(lambda:manager.create("MANUAL"))
        restore=ModernRestoreManager(profile,manager);values["restore_validation_ms"],_=timed(lambda:restore.validate(modern_backup))
        values["diagnostics_generation_ms"],_=timed(lambda:DiagnosticsReporter(profile).health())
        values["candidate_regeneration_setup_ms"],_=timed(lambda:tuple(row for row in repository.tracked_media() if row.mapping_label=="Not mapped"))
    print(json.dumps({key:round(value,4) for key,value in values.items()},indent=2,sort_keys=True))


if __name__=="__main__":main()
