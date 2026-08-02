from __future__ import annotations

import json
import os
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QPushButton

from anime_tracker.gui_qt.covers import CoverImageCache
from anime_tracker.gui_qt.data import ModernRepository, TitleMetadata, resolve_display_title
from anime_tracker.gui_qt.dialogs import AnimeDetailDialog
from anime_tracker.gui_qt.main_window import MainWindow
from anime_tracker.gui_qt.models import AnimeTableModel
from anime_tracker.gui_qt.pages import CoveragePage, FranchisePage, ReviewPage, SettingsPage
from anime_tracker.production.profile import ProductionProfile


ROOT = Path(__file__).parents[1]
PRODUCTION = ROOT / "production_profile"


def _production_copy(tmp_path: Path) -> ProductionProfile:
    profile=ProductionProfile(tmp_path / "production-copy");profile.initialize_directories()
    shutil.copy2(PRODUCTION / "data" / "anime_tracker_modern.db",profile.database_path)
    shutil.copy2(PRODUCTION / "bootstrap.json",profile.bootstrap_path)
    shutil.copy2(PRODUCTION / "settings.json",profile.settings_path)
    return profile


def test_title_resolver_preference_and_all_fallbacks():
    assert resolve_display_title(TitleMetadata(1,"English","Romaji","Native","Legacy"))=="English"
    assert resolve_display_title(TitleMetadata(2,"","Romaji","Native","Legacy"))=="Romaji"
    assert resolve_display_title(TitleMetadata(3,"","","Native","Legacy"))=="Native"
    assert resolve_display_title(TitleMetadata(4,"","","","Legacy"))=="Legacy"
    assert resolve_display_title(TitleMetadata(5))=="AniList 5"


def test_all_active_production_copy_records_resolve_metadata(tmp_path):
    profile=_production_copy(tmp_path);rows=ModernRepository(profile.database_path).tracked_media()
    assert len(rows)==69
    assert all(row.title.strip() for row in rows)
    assert all(not row.title.startswith("AniList ") for row in rows)
    assert sum(bool(row.english) for row in rows)==69
    assert sum(bool(row.romaji) for row in rows)==69
    assert sum(bool(row.native) for row in rows)==69
    assert sum(bool(row.cover_url) for row in rows)==69


def test_tracked_display_read_is_bulk_not_n_plus_one(tmp_path):
    profile=_production_copy(tmp_path);queries=[];real_connect=sqlite3.connect
    def traced(*args,**kwargs):
        connection=real_connect(*args,**kwargs);connection.set_trace_callback(queries.append);return connection
    with patch("anime_tracker.gui_qt.data.sqlite3.connect",side_effect=traced):
        assert len(ModernRepository(profile.database_path).tracked_media())==69
    selects=[query for query in queries if query.lstrip().upper().startswith(("SELECT","WITH"))]
    assert len(selects)<=2


def test_table_detail_review_franchise_and_coverage_use_resolved_titles(qtbot,tmp_path):
    profile=_production_copy(tmp_path);repo=ModernRepository(profile.database_path);rows=repo.tracked_media()
    model=AnimeTableModel(rows);assert model.data(model.index(0,1))==rows[0].title
    detail=AnimeDetailDialog(rows[0]);qtbot.addWidget(detail)
    detail_text=" ".join(label.text() for label in detail.findChildren(QLabel))
    assert rows[0].title in detail_text and "Romaji unknown" not in detail_text
    review=ReviewPage(repo);franchise=FranchisePage(repo);coverage=CoveragePage(repo)
    for widget in (review,franchise,coverage):qtbot.addWidget(widget)
    assert len(review.rows)==8 and all(row["title"] in review.list.item(i).text() for i,row in enumerate(review.rows))
    franchise_text=" ".join(franchise.tree.topLevelItem(i).child(j).text(0) for i in range(franchise.tree.topLevelItemCount()) for j in range(franchise.tree.topLevelItem(i).childCount()))
    assert all(row.title in franchise_text for row in rows)
    coverage_titles={coverage.by_anime.topLevelItem(i).text(0) for i in range(coverage.by_anime.topLevelItemCount())}
    assert {row.title for row in rows}==coverage_titles


def test_relation_targets_and_cover_metadata_are_resolved(tmp_path):
    profile=_production_copy(tmp_path);rows=ModernRepository(profile.database_path).tracked_media()
    relations=[relation for row in rows for relation in row.relations]
    assert relations and all(relation.title and not relation.title.startswith("AniList ") for relation in relations)
    assert all(row.cover_url.startswith("https://") for row in rows)


def test_cover_placeholder_is_graphical_not_text(qtbot,tmp_path):
    cache=CoverImageCache(tmp_path);pixmap=cache.placeholder(52,73)
    assert not pixmap.isNull() and pixmap.width()==52 and pixmap.height()==73
    row=ModernRepository(PRODUCTION / "data" / "anime_tracker_modern.db").tracked_media()[0]
    model=AnimeTableModel((row,));assert model.data(model.index(0,0),Qt.DisplayRole)==""


def test_valid_cached_cover_is_used_without_network(qtbot,tmp_path):
    url="https://images.example.invalid/cover.jpg";cache=CoverImageCache(tmp_path)
    image=QPixmap(20,30);image.fill(Qt.red);assert image.save(str(cache._path(url)),"PNG")
    with patch.object(cache.network,"get") as request:
        loaded=cache.request(url)
    assert not loaded.isNull() and loaded.size()==image.size() and not request.called


def test_notification_controls_change_persist_and_stage_one_does_not_deliver(qtbot,tmp_path):
    profile=_production_copy(tmp_path);repository=ModernRepository(profile.database_path)
    with patch("requests.sessions.Session.request") as delivery_request:
        window=MainWindow(profile,repository,production=True);qtbot.addWidget(window)
        page=window.pages["Settings"];assert isinstance(page,SettingsPage)
        assert all(check.isEnabled() for check in (page.private_notifications,page.shared_notifications,page.windows_notifications))
        page.private_notifications.setChecked(True);page.shared_notifications.setChecked(True);page.windows_notifications.setChecked(True)
        delivery=[button for button in page.findChildren(QPushButton) if button.text()=="Enable delivery"]
        assert delivery and not delivery[0].isEnabled() and "Preview Only" in delivery[0].toolTip()
        window.close();assert not delivery_request.called
    saved=profile.load_settings()
    assert saved["notifications_private_enabled"] and saved["notifications_shared_enabled"] and saved["notifications_windows_enabled"]
    assert profile.load_bootstrap()["notifications_stage"]==1
    restarted=MainWindow(profile,repository,production=True);qtbot.addWidget(restarted);reloaded=restarted.pages["Settings"]
    assert reloaded.private_notifications.isChecked() and reloaded.shared_notifications.isChecked() and reloaded.windows_notifications.isChecked()
    assert not any(path.name.endswith("latest.json") for path in profile.logs_dir.glob("notification*"))


def test_context_specific_filters_and_no_no_match_review(qtbot,tmp_path):
    profile=_production_copy(tmp_path);window=MainWindow(profile,ModernRepository(profile.database_path),production=True);qtbot.addWidget(window)
    airing={window.pages["Currently Airing"].filter.itemText(i) for i in range(window.pages["Currently Airing"].filter.count())}
    finished={window.pages["Finished / Ready to Add"].filter.itemText(i) for i in range(window.pages["Finished / Ready to Add"].filter.count())}
    on_server={window.pages["On Server"].filter.itemText(i) for i in range(window.pages["On Server"].filter.count())}
    assert {"Missing aired episodes","Airing this week","No schedule"}<=airing
    assert {"Partial","Not found","Needs mapping"}<=finished
    assert {"Currently airing","Movie","Series"}<=on_server
    assert all(row["review_type"]!="NO_MATCH" for row in window.pages["Needs Review"].rows)


def test_acceptance_report_and_gui_sources_expose_no_secrets_or_media_writes():
    report=(PRODUCTION/"diagnostics"/"milestone8-acceptance-metadata-counts.json").read_text(encoding="utf-8")
    assert "discord.com/api/webhooks" not in report.casefold() and "jellyfin_media" not in report.casefold()
    gui=ROOT/"src"/"anime_tracker"/"gui_qt"
    source="\n".join((gui/name).read_text(encoding="utf-8") for name in ("data.py","covers.py","dialogs.py","main_window.py","models.py","widgets.py","pages/core.py"))
    assert "Storage Checker" not in source and "requests.post(" not in source
    assert not any(operation in source for operation in ("shutil.move(","os.remove(","Path.unlink("))
