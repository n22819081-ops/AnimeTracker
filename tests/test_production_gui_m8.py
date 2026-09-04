from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

from anime_tracker.gui_qt.application import create_production_application
from anime_tracker.gui_qt.production_dialogs import ProductionMigrationWizard,WIZARD_STEPS
from anime_tracker.production.profile import ProductionProfile
from production_helpers import production_profile


def test_first_production_startup_returns_no_side_effect_wizard_state(tmp_path):
    app,window,profile=create_production_application(tmp_path/"empty-production")
    assert window is None and profile.load_bootstrap()["migration_state"]=="NOT_STARTED"
    assert not profile.root.exists()


def test_migration_wizard_has_all_steps_and_can_be_postponed(qtbot,tmp_path):
    profile=ProductionProfile(tmp_path/"profile");profile.initialize_directories();dialog=ProductionMigrationWizard(profile);qtbot.addWidget(dialog)
    assert dialog.steps.count()==15 and tuple(dialog.steps.item(i).text() for i in range(dialog.steps.count()))==WIZARD_STEPS
    before=profile.load_bootstrap();dialog.reject();assert profile.load_bootstrap()==before


def test_completed_migration_opens_production_window_with_disabled_activation(qtbot,tmp_path):
    profile=production_profile(tmp_path);app,window,value=create_production_application(profile.root);qtbot.addWidget(window)
    assert window.production and "Production Profile" in window.windowTitle()
    settings=window.pages["Settings"];assert not settings.schedule_enabled.isChecked() and not settings.schedule_private.isChecked() and not settings.schedule_shared.isChecked()
    assert not settings.tv.isReadOnly() and not settings.movies.isReadOnly()


def test_launcher_has_explicit_test_reset_and_no_broad_reset():
    root=Path(__file__).parents[1];script=(root/"Modern Anime Tracker"/"Run-AnimeTracker-Modern.ps1").read_text(encoding="utf-8");application=(root/"src"/"anime_tracker"/"gui_qt"/"application.py").read_text(encoding="utf-8")
    assert "--reset-test-profile" in application and "--test-profile" in application
    assert '"--reset-profile"' in script and "was removed" in script
