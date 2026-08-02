from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .data import ModernRepository
from .main_window import MainWindow
from .profile import DEFAULT_PROFILE, ModernProfile


def create_application(profile_path: str | Path = DEFAULT_PROFILE) -> tuple[QApplication, MainWindow]:
    app=QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Anime Tracker Modern"); app.setOrganizationName("Anime Tracker")
    profile=ModernProfile(Path(profile_path)); profile.initialize()
    window=MainWindow(profile,ModernRepository(profile.database_path))
    return app,window


def create_production_application(profile_path=None):
    from ..production.profile import DEFAULT_PRODUCTION_PROFILE,ProductionProfile
    profile=ProductionProfile(Path(profile_path or DEFAULT_PRODUCTION_PROFILE))
    app=QApplication.instance() or QApplication(sys.argv);app.setApplicationName("Anime Tracker");app.setOrganizationName("Anime Tracker")
    if not profile.database_path.is_file():return app,None,profile
    profile.initialize_directories()
    return app,MainWindow(profile,ModernRepository(profile.database_path),production=True),profile


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description="Anime Tracker modern development GUI")
    mode=parser.add_mutually_exclusive_group();mode.add_argument("--test-profile",action="store_true");mode.add_argument("--production-profile",action="store_true")
    parser.add_argument("--profile");parser.add_argument("--reset-test-profile",action="store_true");parser.add_argument("--scheduled-check",action="store_true");parser.add_argument("--offscreen",action="store_true")
    args=parser.parse_args(argv)
    if args.offscreen:os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
    if args.scheduled_check:
        from ..production.scheduled_command import main as scheduled_main
        return scheduled_main((["--profile",args.profile] if args.profile else []))
    if args.test_profile or args.reset_test_profile:
        profile=ModernProfile(Path(args.profile) if args.profile else DEFAULT_PROFILE)
        if args.reset_test_profile:profile.reset()
        app,window=create_application(profile.root);window.show();return app.exec()
    app,window,profile=create_production_application(args.profile)
    if window is None:
        from .production_dialogs import ProductionMigrationWizard
        return 0 if ProductionMigrationWizard(profile).exec()==0 else 0
    window.show();return app.exec()


if __name__=="__main__":raise SystemExit(main())
