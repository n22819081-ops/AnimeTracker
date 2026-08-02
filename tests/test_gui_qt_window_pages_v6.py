from __future__ import annotations

import hashlib
import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from anime_tracker.gui_qt.application import create_application
from anime_tracker.gui_qt.dialogs import AddAnimeDialog, AnimeDetailDialog, LegacyImportPreviewDialog, MatchingReviewDialog
from anime_tracker.gui_qt.main_window import PAGE_LABELS
from anime_tracker.gui_qt.pages import AnimeListPage, CoveragePage, FranchisePage, NotificationsPage, ReviewPage, SettingsPage
from anime_tracker.gui_qt.data import AnimeRow
from anime_tracker.gui_qt.profile import ModernProfile, PROTOTYPE_DATABASE


@pytest.fixture
def window(qtbot,tmp_path):
    profile=ModernProfile(tmp_path/"qt-profile"); profile.initialize(prototype=PROTOTYPE_DATABASE)
    app,value=create_application(profile.root); qtbot.addWidget(value); value.show(); return value


def test_main_window_constructs_separately_and_is_resizable(window):
    assert "Development / Migration Test Profile" in window.windowTitle()
    assert window.minimumWidth()>=1200 and window.minimumHeight()>=760


def test_every_required_page_constructs_and_switches(window,qtbot):
    assert tuple(window.pages)==PAGE_LABELS
    for index,label in enumerate(PAGE_LABELS):
        window.navigation.setCurrentRow(index); qtbot.wait(1)
        assert window.stack.currentWidget() is window.pages[label]


def test_last_page_persists(window,qtbot):
    window.navigation.setCurrentRow(PAGE_LABELS.index("Franchises")); window.close()
    assert window.profile.load_settings()["last_page"]=="Franchises"


def test_startup_performs_no_network_scan_or_webhook_read(window):
    source="\n".join(path.read_text(encoding="utf-8") for path in (Path(__file__).parents[1]/"src"/"anime_tracker"/"gui_qt").rglob("*.py"))
    assert "notification_config"+".json" not in source
    assert "requests.post(" not in source
    assert "build_library_snapshot(" not in source


def test_search_updates_current_table(window,qtbot):
    window.navigation.setCurrentRow(PAGE_LABELS.index("Currently Airing")); page=window.pages["Currently Airing"]
    before=page.table.proxy.rowCount(); window.search.setText("unlikely nonexistent title"); qtbot.wait(1)
    assert before>0 and page.table.proxy.rowCount()==0


def test_status_pages_keep_not_on_server_separate_from_review(window):
    review=window.pages["Needs Review"]; assert isinstance(review,ReviewPage); assert len(review.rows)==5
    assert all(row["review_type"]!="NO_MATCH" for row in review.rows)


def test_finished_page_excludes_complete(window):
    page=window.pages["Finished / Ready to Add"]
    assert all(row.server_status!="COMPLETE" for row in page.table.model.rows)


def test_franchise_shared_scopes_display_separately(window):
    page=window.pages["Franchises"]; assert isinstance(page,FranchisePage)
    labels=[]
    for index in range(page.tree.topLevelItemCount()):
        parent=page.tree.topLevelItem(index)
        labels.extend(parent.child(child).text(4) for child in range(parent.childCount()))
    assert any("UNKNOWN_TARGET" in label for label in labels)


def test_coverage_has_three_read_only_views(window):
    page=window.pages["Jellyfin Coverage"]; assert isinstance(page,CoveragePage)
    assert [page.tabs.tabText(i) for i in range(page.tabs.count())]==["By anime","By server folder","Missing episodes"]
    assert "rename" not in " ".join(button.text().casefold() for button in page.findChildren(type(window.add)))


def test_notifications_has_all_outbox_states_and_no_secret_widget(window):
    page=window.pages["Notifications"]; assert isinstance(page,NotificationsPage)
    assert set(page.tables)=={"PENDING","RETRY_WAIT","DELIVERED","FAILED_PERMANENT","SUPPRESSED","CANCELED"}
    assert "webhook" not in " ".join(label.text().casefold() for label in page.findChildren(type(window.task_status)))


def test_settings_theme_switch_and_read_only_label(window,qtbot):
    page=window.pages["Settings"]; assert isinstance(page,SettingsPage)
    page.theme.setCurrentText("Light"); qtbot.wait(1); assert window.settings["theme"]=="Light"
    assert any("read-only" in label.text().casefold() for label in page.findChildren(type(window.task_status)))


def test_import_preview_exact_counts(window,qtbot):
    dialog=LegacyImportPreviewDialog(window.repository,window); qtbot.addWidget(dialog)
    assert "Preview" in dialog.windowTitle()
    assert window.repository.import_preview()=={"active_titles":69,"archived_orphans":421,"baseline_rows":1312,"mappings":1,"rejections":11,"candidates":14}


def test_detail_shows_status_dimensions_and_hides_full_path(window,qtbot):
    row=window.repository.tracked_media()[0]; dialog=AnimeDetailDialog(row,window); qtbot.addWidget(dialog)
    text=" ".join(label.text() for label in dialog.findChildren(type(window.task_status)))
    assert "AniList:" in text and "Tracker:" in text and "Server:" in text
    assert ":\\" not in text


def test_add_dialog_search_id_url_pagination_and_no_automatic_mapping(window,qtbot):
    calls=[]
    result={"title":"Example Season 2","alternate_title":"Example 2","format":"TV","year":2026,"status":"RELEASING","related":[{"title":"Example OVA","format":"OVA","year":2026}]}
    dialog=AddAnimeDialog(lambda query,year,format_value:(calls.append((query,year,format_value)) or (result,)),window); qtbot.addWidget(dialog)
    for query in ("Example","12345","https://anilist.co/anime/12345"):
        dialog.query.setText(query); dialog.run_search(); assert dialog.results.rowCount()==1
    dialog.results.selectRow(0); qtbot.wait(1)
    assert len(calls)==3 and dialog.related.count()==1 and dialog.page_label.text()=="Page 1"
    assert window.repository.import_preview()["mappings"]==1


def test_matching_review_blocks_stale_candidate(window,qtbot):
    dialog=MatchingReviewDialog({"title":"Season 2","stale":True,"candidates":[{"target":"Season 02","confidence":"STRONG","score":120,"evidence":"Exact season"}]},window); qtbot.addWidget(dialog)
    assert not dialog.confirm.isEnabled()


def test_scan_requires_explicit_test_paths_and_does_not_start(window,qtbot):
    assert not window.workers
    with patch("PySide6.QtWidgets.QMessageBox.information",return_value=None):window.start_scan()
    assert not window.workers


def test_franchise_many_to_one_seasons_remain_distinct(qtbot):
    rows=(
        AnimeRow(100,"Example Anime Season 1","","","TV","",2024,"FINISHED","On Server","COMPLETE","12/12","","NONE","",mapping_label="SERIES_SEASON · Season 01"),
        AnimeRow(200,"Example Anime Season 2","","","TV","",2026,"RELEASING","Currently Airing","PARTIAL","3/4","","NONE","",mapping_label="SERIES_SEASON · Season 02"),
        AnimeRow(300,"Example Anime OVA","","","OVA","",2025,"FINISHED","On Server","COMPLETE","1/1","","NONE","",mapping_label="SERIES_SPECIALS · Season 00"),
    )
    repo=type("Repo",(),{"tracked_media":lambda self:rows})()
    page=FranchisePage(repo); qtbot.addWidget(page)
    labels=[]
    for i in range(page.tree.topLevelItemCount()):
        parent=page.tree.topLevelItem(i); labels.extend(parent.child(j).text(4) for j in range(parent.childCount()))
    assert {label.rsplit(" ",1)[-1] for label in labels}=={"00","01","02"}


def test_column_width_and_test_paths_persist(window):
    page=window.pages["Currently Airing"]; page.table.view.setColumnWidth(1,333)
    settings=window.pages["Settings"]; settings.tv.setText(r"C:\Synthetic\TV"); window.close()
    saved=window.profile.load_settings(); assert saved["test_tv_path"]==r"C:\Synthetic\TV"; assert saved["table_columns"]["Currently Airing"][1]==333
