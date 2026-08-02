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


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description="Anime Tracker modern development GUI")
    parser.add_argument("--profile",default=str(DEFAULT_PROFILE)); parser.add_argument("--reset-profile",action="store_true"); parser.add_argument("--offscreen",action="store_true")
    args=parser.parse_args(argv)
    if args.offscreen:os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
    profile=ModernProfile(Path(args.profile))
    if args.reset_profile:profile.reset()
    app,window=create_application(profile.root); window.show(); return app.exec()


if __name__=="__main__":raise SystemExit(main())
