from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from anime_tracker.gui_qt.application import main
from anime_tracker.production.adoption import ProfileAdoptionService,detect_project_profile
from anime_tracker.production.credentials import SecretValue
from anime_tracker.production.profile import ProductionProfile
from anime_tracker.runtime import APP_VERSION, BUILD_IDENTIFIER, SCHEMA_VERSION, validate_profile_override


def _counts(path: Path) -> dict[str, int]:
    with sqlite3.connect(path) as connection:
        return {
            "active": connection.execute("SELECT count(*) FROM tracked_media WHERE archived_at IS NULL").fetchone()[0],
            "archive": connection.execute("SELECT count(*) FROM archived_legacy_records").fetchone()[0],
            "baseline": connection.execute("SELECT count(*) FROM shared_announcement_baselines_v2").fetchone()[0],
            "reviews": connection.execute("SELECT count(*) FROM review_cases WHERE state IN ('OPEN','ACKNOWLEDGED')").fetchone()[0],
        }


def test_release_version_is_consistent():
    root=Path(__file__).parents[1]
    assert (APP_VERSION,BUILD_IDENTIFIER,SCHEMA_VERSION)==("1.0.0","1.0.0-rc1",6)
    assert 'version = "1.0.0"' in (root/"pyproject.toml").read_text(encoding="utf-8")
    assert '#define MyAppVersion "1.0.0"' in (root/"packaging"/"AnimeTracker.iss").read_text(encoding="utf-8")


def test_clean_profile_is_empty_safe_and_schema_current(tmp_path):
    profile=ProductionProfile(tmp_path/"clean profile");profile.initialize_new()
    assert _counts(profile.database_path)=={"active":0,"archive":0,"baseline":0,"reviews":0}
    assert profile.load_bootstrap()["notifications_stage"]==1
    assert not profile.load_bootstrap()["scheduled_checks_enabled"]
    with sqlite3.connect(profile.database_path) as connection:
        assert max(row[0] for row in connection.execute("SELECT version FROM schema_migrations"))==SCHEMA_VERSION
        assert connection.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall()==[]


def test_clean_profile_jellyfin_roots_can_be_configured_without_scanning(qtbot,tmp_path):
    from anime_tracker.gui_qt.data import ModernRepository
    from anime_tracker.gui_qt.main_window import MainWindow
    profile=ProductionProfile(tmp_path/"clean");profile.initialize_new();window=MainWindow(profile,ModernRepository(profile.database_path),production=True);qtbot.addWidget(window)
    settings=window.pages["Settings"];settings.tv.setText(str(tmp_path/"TV Library"));settings.movies.setText(str(tmp_path/"Movie Library"));window.close()
    saved=profile.load_settings();assert saved["test_tv_path"].endswith("TV Library") and saved["test_movie_path"].endswith("Movie Library")
    assert not any(profile.logs_dir.iterdir())


def test_profile_adoption_copies_verifies_and_retains_source(tmp_path):
    source=ProductionProfile(tmp_path/"project profile");source.initialize_new();source.save_settings({"theme":"Dark","jellyfin_roots":[]})
    target=ProductionProfile(tmp_path/"installed profile")
    result=ProfileAdoptionService(source,target).adopt(approved=True)
    assert result.adopted and result.source_retained and source.database_path.is_file()
    assert result.integrity=="ok" and result.foreign_key_violations==0 and result.schema_version==SCHEMA_VERSION
    assert _counts(target.database_path)==_counts(source.database_path)
    assert (target.diagnostics_dir/"profile-adoption.json").is_file()
    assert (target.root.parent/"AnimeTracker Adoption Backups"/result.backup_reference/"manifest.json").is_file()


def test_profile_adoption_requires_confirmation(tmp_path):
    source=ProductionProfile(tmp_path/"source");source.initialize_new()
    with pytest.raises(PermissionError):ProfileAdoptionService(source,ProductionProfile(tmp_path/"target")).adopt(approved=False)


def test_project_profile_detection_and_postpone_are_read_only(qtbot,tmp_path):
    from anime_tracker.gui_qt.production_dialogs import FirstRunDialog
    source=ProductionProfile(tmp_path/"source");source.initialize_new();target=ProductionProfile(tmp_path/"target")
    assert detect_project_profile(source.root)==source.root
    dialog=FirstRunDialog(target,source);qtbot.addWidget(dialog);dialog.reject()
    assert not target.root.exists() and source.database_path.is_file()


def test_adoption_failure_rolls_back_target_and_retains_source(tmp_path):
    source=ProductionProfile(tmp_path/"source");source.initialize_new();target=ProductionProfile(tmp_path/"target");service=ProfileAdoptionService(source,target)
    with patch.object(service,"_copy_profile",side_effect=OSError("controlled copy failure")),pytest.raises(OSError):service.adopt(approved=True)
    assert source.database_path.is_file() and not target.root.exists()


def test_adoption_verifies_separate_dpapi_references_without_revealing_values(tmp_path):
    source=ProductionProfile(tmp_path/"source");source.initialize_new();now="2026-08-02T00:00:00+00:00"
    rows=(("private-ref","PRIVATE_TRACKER"),("shared-ref","SHARED_ANNOUNCEMENT"))
    with sqlite3.connect(source.database_path) as connection:
        connection.executemany("INSERT INTO credential_references(reference_id,profile_id,channel_purpose,provider,credential_identifier,secret_present,enabled,created_at,updated_at) VALUES(?,'production',?,'WINDOWS_DPAPI',?,1,0,?,?)",((reference,purpose,f"{reference}.dpapi",now,now) for reference,purpose in rows));connection.commit()
    class RedactedStore:
        def __init__(self,directory):self.directory=directory
        def retrieve_secret(self,reference):assert reference in {"private-ref","shared-ref"};return SecretValue("https://validated.invalid/redacted")
    target=ProductionProfile(tmp_path/"target")
    with patch("anime_tracker.production.adoption.DpapiCredentialStore",RedactedStore):result=ProfileAdoptionService(source,target).adopt(approved=True)
    assert result.credential_state=="VERIFIED"
    with sqlite3.connect(target.database_path) as connection:
        assert connection.execute("SELECT channel_purpose,secret_present,enabled FROM credential_references ORDER BY channel_purpose").fetchall()==[("PRIVATE_TRACKER",1,0),("SHARED_ANNOUNCEMENT",1,0)]


def test_profile_override_requires_absolute_application_owned_path(tmp_path):
    assert validate_profile_override(tmp_path/"profile").is_absolute()
    with pytest.raises(ValueError):validate_profile_override(Path("relative-profile"))


def test_diagnostics_and_smoke_test_entry_points(qtbot,tmp_path,capsys):
    profile=ProductionProfile(tmp_path/"profile");profile.initialize_new()
    assert main(["--diagnostics","--profile",str(profile.root)])==0
    diagnostic=json.loads(capsys.readouterr().out);assert diagnostic["version"]==APP_VERSION and diagnostic["schema_version"]==SCHEMA_VERSION
    assert main(["--smoke-test","--profile",str(profile.root),"--offscreen"])==0
    smoke=json.loads(capsys.readouterr().out);assert smoke["status"]=="PASS" and smoke["page_count"]==12 and smoke["active_titles"]==0


def test_packaging_is_windowed_per_user_and_preserves_data():
    root=Path(__file__).parents[1];spec=(root/"packaging"/"anime_tracker.spec").read_text(encoding="utf-8");installer=(root/"packaging"/"AnimeTracker.iss").read_text(encoding="utf-8")
    assert "console=False" in spec and "name='Anime Tracker'" in spec and "PySide6.QtNetwork" in spec
    assert "PrivilegesRequired=lowest" in installer and "DefaultDirName={localappdata}\\Programs\\Anime Tracker" in installer
    assert "scheduled" not in installer.casefold() and "production_profile" not in installer
    assert "UninstallDelete" in installer and "User data" in installer


def test_packaged_sources_have_no_shell_eval_or_reset_profile():
    root=Path(__file__).parents[1];sources="\n".join(path.read_text(encoding="utf-8") for path in (root/"src"/"anime_tracker").rglob("*.py"))
    assert "shell=True" not in sources and "eval(" not in sources and '"--reset-profile"' not in sources


def test_release_artifact_names():
    tools=(Path(__file__).parents[1]/"packaging"/"release_tools.py").read_text(encoding="utf-8")
    assert "Anime-Tracker-Setup-{APP_VERSION}.exe" in tools
    assert "Anime-Tracker-Portable-{APP_VERSION}.zip" in tools


@pytest.mark.skipif(not (Path(__file__).parents[1]/"packaging"/"installer-staging"/"Anime Tracker.bin").is_file(),reason="release build not present")
def test_built_pe_has_version_icon_and_windowed_subsystem():
    import pefile
    root=Path(__file__).parents[1];pe=pefile.PE(str(root/"packaging"/"installer-staging"/"Anime Tracker.bin"))
    assert pe.OPTIONAL_HEADER.Subsystem==2
    assert pe.VS_FIXEDFILEINFO[0].FileVersionMS==(1<<16)
    resource_ids={entry.id for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries}
    assert 3 in resource_ids and 16 in resource_ids


@pytest.mark.skipif(not (Path(__file__).parents[1]/"dist"/"Anime Tracker").is_dir(),reason="release build not present")
def test_built_distribution_has_required_runtime_plugins_and_no_user_data():
    root=Path(__file__).parents[1];dist=root/"dist"/"Anime Tracker";plugins=dist/"_internal"/"PySide6"/"plugins"
    for path in (plugins/"platforms"/"qwindows.dll",plugins/"imageformats"/"qjpeg.dll",plugins/"styles"/"qmodernwindowsstyle.dll",plugins/"tls"/"qschannelbackend.dll",dist/"_internal"/"sqlite3.dll",dist/"_internal"/"Create-ModernScheduledTask.ps1"):assert path.is_file()
    names={path.name.casefold() for path in dist.rglob("*") if path.is_file()}
    assert not any(name.endswith((".db",".sqlite")) for name in names)
    assert not ({"logs","backups","production_profile"}&{path.name.casefold() for path in dist.rglob("*")})


@pytest.mark.skipif(not (Path(__file__).parents[1]/"release"/"1.0.0"/"Anime-Tracker-Portable-1.0.0.zip").is_file(),reason="release build not present")
def test_portable_zip_matches_onedir_and_has_no_python_source_or_profile():
    import zipfile
    path=Path(__file__).parents[1]/"release"/"1.0.0"/"Anime-Tracker-Portable-1.0.0.zip"
    with zipfile.ZipFile(path) as archive:
        names=archive.namelist();assert archive.testzip() is None and len(names)==224
    assert "Anime Tracker/Anime Tracker.exe" in names
    assert not any(name.casefold().endswith((".py",".db",".sqlite")) for name in names)
    assert not any("production_profile" in name.casefold() or "storage checker" in name.casefold() for name in names)
