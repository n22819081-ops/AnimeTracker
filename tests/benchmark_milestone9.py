"""Milestone 9 release-candidate performance benchmark using disposable data."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

from PySide6.QtWidgets import QApplication

from anime_tracker.gui_qt.data import ModernRepository
from anime_tracker.gui_qt.main_window import MainWindow
from anime_tracker.production.adoption import ProfileAdoptionService
from anime_tracker.production.backup_restore import ModernBackupManager
from anime_tracker.production.diagnostics import DiagnosticsReporter
from anime_tracker.production.profile import ProductionProfile
from anime_tracker.production.scheduled import ScheduledCheckRunner


ROOT=Path(__file__).parents[1]
SOURCE=ProductionProfile(ROOT/"production_profile")


def timed(operation):
    started=time.perf_counter();value=operation();return round((time.perf_counter()-started)*1000,3),value


def main():
    values={};app=QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);profile=ProductionProfile(root/"profile");profile.initialize_directories()
        shutil.copy2(SOURCE.database_path,profile.database_path);shutil.copy2(SOURCE.bootstrap_path,profile.bootstrap_path);shutil.copy2(SOURCE.settings_path,profile.settings_path)
        values["existing_profile_repository_ms"],repository=timed(lambda:ModernRepository(profile.database_path))
        values["load_69_rows_ms"],rows=timed(repository.tracked_media)
        values["dashboard_population_ms"],_=timed(repository.dashboard_counts)
        values["main_window_12_pages_ms"],window=timed(lambda:MainWindow(profile,repository,production=True))
        values["all_page_navigation_ms"],_=timed(lambda:[window.show_page(name) for name in window.pages])
        values["search_filter_ms"],_=timed(lambda:[window.search.setText(value) for value in ("season","movie","")])
        values["diagnostics_ms"],_=timed(lambda:DiagnosticsReporter(profile).health())
        values["backup_ms"],_=timed(lambda:ModernBackupManager(profile).create("M9_BENCHMARK"))
        clean=ProductionProfile(root/"clean");values["clean_profile_creation_ms"],_=timed(clean.initialize_new)
        clean_bootstrap=clean.load_bootstrap();clean_bootstrap.update({"anilist_refresh_enabled":False,"jellyfin_scan_enabled":False});clean.save_bootstrap(clean_bootstrap)
        values["scheduled_check_disabled_ms"],scheduled=timed(lambda:ScheduledCheckRunner(clean).run())
        adopted=ProductionProfile(root/"adopted");values["profile_adoption_verification_ms"],_=timed(lambda:ProfileAdoptionService(profile,adopted).adopt(approved=True))
        window.deleteLater();app.processEvents()
    print(json.dumps({"measurements_ms":values,"rows":len(rows),"scheduled_status":scheduled.status},indent=2,default=str))


if __name__=="__main__":main()
