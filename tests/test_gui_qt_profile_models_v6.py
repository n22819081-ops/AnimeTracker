from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

import pytest
from PySide6.QtCore import Qt

from anime_tracker.gui_qt.data import AnimeRow, ModernRepository
from anime_tracker.gui_qt.models import AnimeFilterProxy, AnimeTableModel, COLUMNS
from anime_tracker.gui_qt.profile import LIVE_DATABASE, ModernProfile, PROTOTYPE_DATABASE, default_settings


@pytest.fixture
def profile(tmp_path):
    value=ModernProfile(tmp_path/"profile"); value.initialize(prototype=PROTOTYPE_DATABASE); return value


def test_empty_profile_imports_disposable_prototype(profile):
    assert profile.database_path.exists()
    assert profile.database_path.resolve()!=LIVE_DATABASE.resolve()


def test_profile_counts_and_no_row_loss(profile):
    preview=ModernRepository(profile.database_path).import_preview()
    assert preview["active_titles"]==69
    assert preview["archived_orphans"]==421
    assert preview["baseline_rows"]==1312


def test_settings_defaults_and_persistence(profile):
    settings=profile.load_settings(); assert settings["theme"]=="Dark"
    settings["theme"]="Light"; settings["last_page"]="Franchises"; profile.save_settings(settings)
    assert profile.load_settings()["theme"]=="Light"
    assert profile.load_settings()["last_page"]=="Franchises"


def test_corrupt_settings_falls_back(profile):
    profile.settings_path.write_text("not json",encoding="utf-8")
    assert profile.load_settings()["settings_recovered"] is True


def test_settings_strip_secret_like_keys(profile):
    profile.save_settings({"theme":"Dark","webhook_value":"secret","api_secret":"secret"})
    text=profile.settings_path.read_text(encoding="utf-8")
    assert "secret" not in text


def test_reset_profile_restores_migration_copy(profile):
    original=ModernRepository(profile.database_path).import_preview()
    profile.reset(prototype=PROTOTYPE_DATABASE)
    assert ModernRepository(profile.database_path).import_preview()==original


def test_repository_returns_69_typed_rows(profile):
    rows=ModernRepository(profile.database_path).tracked_media()
    assert len(rows)==69
    assert all(row.title and row.anilist_id for row in rows)


def test_dashboard_needs_review_uses_real_cases_not_not_on_server(profile):
    repo=ModernRepository(profile.database_path); counts=repo.dashboard_counts()
    not_on_server=sum(row.server_status=="NOT_ON_SERVER" for row in repo.tracked_media())
    assert not_on_server==64
    assert counts["Needs Review"]==len(repo.review_rows())==5


def test_on_server_count_requires_complete_coverage(profile):
    repo=ModernRepository(profile.database_path)
    assert repo.dashboard_counts()["On Server"]==sum(row.server_status=="COMPLETE" for row in repo.tracked_media())


def test_table_columns_and_data(qtbot):
    row=AnimeRow(1,"Example","Romaji","Native","TV","SPRING",2026,"RELEASING","Currently Airing","PARTIAL","3/4","5","NONE","now")
    model=AnimeTableModel((row,)); assert model.rowCount()==1; assert [name for name,_ in COLUMNS][:2]==["Cover","Title"]
    assert model.data(model.index(0,1))=="Example"


def test_table_search_filter_sort_and_update(qtbot):
    rows=(
        AnimeRow(1,"Alpha","","","TV","",2026,"RELEASING","Currently Airing","PARTIAL","3/4","","NONE",""),
        AnimeRow(2,"Beta Movie","","","MOVIE","",2025,"FINISHED","On Server","COMPLETE","1/1","","NONE",""),
    )
    model=AnimeTableModel(rows); proxy=AnimeFilterProxy(); proxy.setSourceModel(model)
    proxy.set_search("movie complete"); assert proxy.rowCount()==1
    proxy.set_search(""); proxy.set_status_filter("On Server"); assert proxy.rowCount()==1
    updated=replace(rows[0],coverage="4/4"); model.update_row(updated); assert model.rows[0].coverage=="4/4"


def test_repository_does_not_retain_connection(profile):
    repo=ModernRepository(profile.database_path)
    assert set(repo.__dict__)=={"database_path"}
