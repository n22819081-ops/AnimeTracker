from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ..runtime import APP_NAME,APP_VERSION,default_profile_root,packaged_resource,validate_profile_override
from .data import ModernRepository
from .main_window import MainWindow
from .profile import DEFAULT_PROFILE,ModernProfile


def _configure_application(app:QApplication)->None:
    app.setApplicationName(APP_NAME);app.setApplicationVersion(APP_VERSION);app.setOrganizationName(APP_NAME)
    icon=packaged_resource("assets","anime_tracker.ico")
    if icon.is_file():app.setWindowIcon(QIcon(str(icon)))


def _emit_json(value:dict,path:Path|None=None)->None:
    rendered=json.dumps(value,indent=2,default=str)
    if path is not None:
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(rendered+"\n",encoding="utf-8")
    if sys.stdout is not None:print(rendered)


def create_application(profile_path:str|Path=DEFAULT_PROFILE)->tuple[QApplication,MainWindow]:
    app=QApplication.instance() or QApplication(sys.argv);_configure_application(app)
    profile=ModernProfile(Path(profile_path));profile.initialize();window=MainWindow(profile,ModernRepository(profile.database_path));return app,window


def create_production_application(profile_path=None):
    from ..production.profile import ProductionProfile
    profile=ProductionProfile(Path(profile_path or default_profile_root()));app=QApplication.instance() or QApplication(sys.argv);_configure_application(app)
    if not profile.database_path.is_file():return app,None,profile
    profile.initialize_directories();return app,MainWindow(profile,ModernRepository(profile.database_path),production=True),profile


def main(argv=None)->int:
    parser=argparse.ArgumentParser(description=f"{APP_NAME} {APP_VERSION}")
    mode=parser.add_mutually_exclusive_group();mode.add_argument("--test-profile",action="store_true");mode.add_argument("--production-profile",action="store_true")
    parser.add_argument("--profile");parser.add_argument("--reset-test-profile",action="store_true");parser.add_argument("--confirm-test-reset");parser.add_argument("--scheduled-check",action="store_true");parser.add_argument("--diagnostics",action="store_true");parser.add_argument("--smoke-test",action="store_true",help=argparse.SUPPRESS);parser.add_argument("--offscreen",action="store_true")
    args=parser.parse_args(argv)
    if args.offscreen:os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
    profile_path=validate_profile_override(Path(args.profile)) if args.profile else default_profile_root()
    if args.scheduled_check:
        from ..production.scheduled_command import main as scheduled_main
        return scheduled_main(["--profile",str(profile_path)])
    if args.diagnostics:
        from ..production.diagnostics import DiagnosticsReporter
        from ..production.profile import ProductionProfile
        profile=ProductionProfile(profile_path);value=DiagnosticsReporter(profile).health(local_only=False);_emit_json(value,profile.diagnostics_dir/"diagnostics-latest.json" if profile.root.exists() else None);return 0 if profile.database_path.is_file() else 2
    if args.smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
        app,window,profile=create_production_application(profile_path)
        if window is None:
            _emit_json({"status":"PROFILE_NOT_INITIALIZED","version":APP_VERSION});return 2
        summary={"status":"PASS","version":APP_VERSION,"window_title":window.windowTitle(),"pages":list(window.pages),"page_count":len(window.pages),"active_titles":len(window.repository.tracked_media())}
        window.deleteLater();app.processEvents();_emit_json(summary,profile.diagnostics_dir/"smoke-test-latest.json");return 0
    if args.test_profile or args.reset_test_profile:
        if args.reset_test_profile and (not args.profile or args.confirm_test_reset!="RESET TEST PROFILE"):parser.error("Test reset requires --profile and --confirm-test-reset 'RESET TEST PROFILE'.")
        profile=ModernProfile(profile_path if args.profile else DEFAULT_PROFILE)
        if args.reset_test_profile:profile.reset()
        app,window=create_application(profile.root);window.show();return app.exec()
    app,window,profile=create_production_application(profile_path)
    if window is None:
        from ..production.adoption import ProfileAdoptionService,detect_project_profile
        from ..production.profile import ProductionProfile
        from .production_dialogs import FirstRunDialog,ProfileAdoptionDialog
        existing_path=detect_project_profile();existing=ProductionProfile(existing_path) if existing_path and existing_path.resolve()!=profile.root.resolve() else None
        first=FirstRunDialog(profile,existing)
        if first.exec()!=FirstRunDialog.Accepted:return 0
        if first.choice=="CLEAN":profile.initialize_new()
        elif first.choice=="ADOPT" and existing:
            if ProfileAdoptionDialog(ProfileAdoptionService(existing,profile)).exec()!=ProfileAdoptionDialog.Accepted:return 0
        elif first.choice=="USE_EXISTING" and existing:profile=existing
        else:return 0
        app,window,profile=create_production_application(profile.root)
        if window is None:return 2
    window.show();return app.exec()


if __name__=="__main__":raise SystemExit(main())
