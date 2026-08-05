from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

from PySide6.QtWidgets import QLabel

from anime_tracker.gui_qt.data import ModernRepository
from anime_tracker.gui_qt.main_window import MainWindow
from anime_tracker.gui_qt.production_dialogs import FirstRunDialog,ProfileAdoptionDialog
from anime_tracker.production.adoption import ProfileAdoptionService,detect_project_profile,validate_project_profile
from anime_tracker.production.profile import ProductionProfile
from anime_tracker.runtime import PROJECT_PRODUCTION_PROFILE,system_drive_root


ROOT=Path(__file__).parents[1]
PRODUCTION=ROOT/"production_profile"


def _hash(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _profile_state(root:Path)->tuple:
    return tuple((str(path.relative_to(root)),path.stat().st_size,path.stat().st_mtime_ns) for path in sorted(root.rglob("*")) if path.is_file())


def _production_copy(tmp_path:Path)->ProductionProfile:
    profile=ProductionProfile(tmp_path/"project-local-production");profile.initialize_directories()
    shutil.copy2(PRODUCTION/"data"/"anime_tracker_modern.db",profile.database_path)
    shutil.copy2(PRODUCTION/"bootstrap.json",profile.bootstrap_path)
    shutil.copy2(PRODUCTION/"settings.json",profile.settings_path)
    return profile


def test_system_drive_candidate_is_absolute_and_independent_of_working_directory(monkeypatch,tmp_path):
    monkeypatch.chdir(tmp_path)
    assert system_drive_root("C:")==Path("C:\\").resolve()
    assert PROJECT_PRODUCTION_PROFILE==Path("C:\\AnimeTracker\\production_profile")
    assert PROJECT_PRODUCTION_PROFILE.is_absolute()
    assert detect_project_profile()==Path("C:\\AnimeTracker\\production_profile")


def test_existing_profile_validation_is_read_only_redacted_and_complete():
    before={name:_hash(PRODUCTION/name) for name in (Path("data/anime_tracker_modern.db"),Path("bootstrap.json"),Path("settings.json"))}
    validation=validate_project_profile()
    after={name:_hash(PRODUCTION/name) for name in before}
    assert validation.valid and validation.integrity=="ok" and validation.foreign_key_violations==0 and validation.schema_version==6
    assert {key:validation.counts[key] for key in ("active_titles","archived_records","baseline_rows")}=={"active_titles":69,"archived_records":421,"baseline_rows":1312}
    assert validation.counts["review_cases"]>=0 and validation.counts["candidates"]>=0
    assert {key:validation.counts[key] for key in ("mappings","rejections","outbox")}=={"mappings":1,"rejections":11,"outbox":0}
    assert validation.credential_state==(
        {"channel_purpose":"PRIVATE_TRACKER","provider":"WINDOWS_DPAPI","configured":True,"enabled":False},
        {"channel_purpose":"SHARED_ANNOUNCEMENT","provider":"WINDOWS_DPAPI","configured":True,"enabled":False},
    )
    assert before==after and "reference" not in repr(validation.credential_state).casefold()


def test_valid_profile_enables_both_first_run_actions_and_displays_path(qtbot,tmp_path):
    validation=validate_project_profile();existing=ProductionProfile(validation.path);target=ProductionProfile(tmp_path/"target")
    dialog=FirstRunDialog(target,existing,validation=validation);qtbot.addWidget(dialog)
    text=" ".join(label.text() for label in dialog.findChildren(QLabel))
    assert dialog.adopt.isEnabled() and dialog.use_existing.isEnabled()
    assert str(PROJECT_PRODUCTION_PROFILE) in text and "69 active titles" in text and "1312 baselines" in text


def test_invalid_profile_disables_actions_with_explanation(qtbot,tmp_path):
    root=tmp_path/"invalid";root.mkdir();validation=validate_project_profile(root);target=ProductionProfile(tmp_path/"target")
    dialog=FirstRunDialog(target,None,validation=validation);qtbot.addWidget(dialog)
    text=" ".join(label.text() for label in dialog.findChildren(QLabel))
    assert not dialog.adopt.isEnabled() and not dialog.use_existing.isEnabled()
    assert str(root) in text and "database was not found" in text.casefold()


def test_opening_first_run_screen_performs_no_existing_profile_writes(qtbot,tmp_path):
    before=_profile_state(PRODUCTION);validation=validate_project_profile();dialog=FirstRunDialog(ProductionProfile(tmp_path/"target"),ProductionProfile(validation.path),validation=validation);qtbot.addWidget(dialog)
    assert _profile_state(PRODUCTION)==before and not (tmp_path/"target").exists()


def test_database_only_profile_does_not_require_bootstrap_or_source_tree(tmp_path,monkeypatch):
    root=tmp_path/"relocated profile";(root/"data").mkdir(parents=True);shutil.copy2(PRODUCTION/"data"/"anime_tracker_modern.db",root/"data"/"anime_tracker_modern.db")
    monkeypatch.chdir(tmp_path);validation=validate_project_profile(root)
    assert validation.valid and not validation.bootstrap_present and validation.counts["active_titles"]==69


def test_project_local_mode_opens_all_69_titles_and_all_pages(qtbot,tmp_path):
    profile=_production_copy(tmp_path);window=MainWindow(profile,ModernRepository(profile.database_path),production=True);qtbot.addWidget(window)
    assert len(window.repository.tracked_media())==69 and len(window.pages)==12
    assert profile.load_bootstrap()["notifications_stage"]==1


def test_adoption_preview_shows_source_target_and_verified_counts(qtbot,tmp_path):
    source=ProductionProfile(PRODUCTION);target=ProductionProfile(tmp_path/"adopted");before=_profile_state(PRODUCTION);service=ProfileAdoptionService(source,target);preview=service.preview()
    dialog=ProfileAdoptionDialog(service);qtbot.addWidget(dialog);text=" ".join(label.text() for label in dialog.findChildren(QLabel))
    assert preview["available"] and preview["source"]==str(PROJECT_PRODUCTION_PROFILE) and preview["target"]==str(target.root.resolve())
    assert preview["counts"]["active_titles"]==69 and preview["counts"]["archived_records"]==421 and preview["counts"]["baseline_rows"]==1312
    assert str(PROJECT_PRODUCTION_PROFILE) in text and str(target.root.resolve()) in text and "69 active" in text
    assert _profile_state(PRODUCTION)==before and not target.root.exists()
