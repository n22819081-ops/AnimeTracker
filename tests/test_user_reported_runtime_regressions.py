from __future__ import annotations

import os
import sqlite3
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

from anime_tracker.gui_qt.data import AnimeRow,ModernRepository
from anime_tracker.gui_qt.dialogs import ServerFolderDialog
from anime_tracker.gui_qt.pages.core import MoviesPage,NotificationsPage
from anime_tracker.notifications_v2.enums import DeliveryResultType
from anime_tracker.notifications_v2.models import DeliveryResult
from anime_tracker.production.notifications import ProductionManualAnnouncementService
from anime_tracker.services.anilist.client import AniListGraphQLClient
from production_helpers import production_profile


def test_single_manual_folder_search_auto_selects_and_enables_confirm(qtbot):
    choice={"display_name":"Beautiful Bones - Sakurako's Investigation (2015)","library_kind":"TV","scope_label":"Season 01","year":2015,"path":r"I:\TV\Beautiful Bones","season_number":1}
    dialog=ServerFolderDialog((choice,));qtbot.addWidget(dialog);dialog.search.setText("Beautiful Bones")
    assert dialog.table.rowCount()==1 and dialog.ok.isEnabled() and dialog.selected_choice()==choice


def test_movies_excludes_confirmed_on_server_titles(qtbot):
    pending=AnimeRow(1,"Pending Movie","","","MOVIE","",2026,"FINISHED","Finished / Ready to Add","NOT_ON_SERVER","NONE","","","2026")
    complete=AnimeRow(2,"Fragtime","","","MOVIE","",2019,"FINISHED","On Server","COMPLETE","COMPLETE","","","2026")
    repo=SimpleNamespace(tracked_media=lambda:(pending,complete),cover_cache_dir=None)
    page=MoviesPage(repo);qtbot.addWidget(page)
    assert [row.title for row in page.table.model.rows]==["Pending Movie"]


def test_review_rows_are_grouped_by_title(tmp_path):
    profile=production_profile(tmp_path);repo=ModernRepository(profile.database_path)
    with sqlite3.connect(profile.database_path) as connection:
        duplicate=connection.execute("SELECT anilist_id FROM review_cases WHERE state IN ('OPEN','ACKNOWLEDGED') GROUP BY anilist_id HAVING count(*)>1 LIMIT 1").fetchone()
        if duplicate is None:return
        expected=connection.execute("SELECT count(*) FROM review_cases WHERE anilist_id=? AND state IN ('OPEN','ACKNOWLEDGED')",duplicate).fetchone()[0]
    matches=[item for item in repo.review_rows() if item["anilist_id"]==duplicate[0]]
    assert len(matches)==1 and len(matches[0]["review_ids"])==expected


def test_anilist_disabled_response_has_truthful_user_message():
    response=SimpleNamespace(status_code=403,json=lambda:{"errors":[{"message":"The AniList API has been temporarily disabled due to severe stability issues."}]})
    error=AniListGraphQLClient()._response_error(response)
    assert error.error_type.value=="CONNECTION_ERROR" and "Your search is valid" in error.safe_message


def test_notifications_page_exposes_explicit_shared_composer(qtbot):
    row=AnimeRow(2,"Fragtime","","","MOVIE","",2019,"FINISHED","On Server","COMPLETE","COMPLETE","","","2026")
    repo=SimpleNamespace(tracked_media=lambda:(row,),notification_rows=lambda:())
    page=NotificationsPage(repo,production=True);qtbot.addWidget(page);page.available.item(0).setSelected(True)
    assert page.send_announcement.isEnabled() and "Fragtime" in page._announcement_text()


def test_manual_announcement_requires_approval_and_records_delivery(tmp_path):
    profile=production_profile(tmp_path)
    class Store:
        def retrieve_secret(self,_):return SimpleNamespace(reveal=lambda:"https://example.invalid/webhook")
    class Adapter:
        def deliver(self,secret,message,**kwargs):assert secret and "Fragtime" in message.body;return DeliveryResult(DeliveryResultType.DELIVERED)
    service=ProductionManualAnnouncementService(profile,Store(),Adapter())
    try:service.send_new_on_server(({"anilist_id":108487,"title":"Fragtime"},),approved=False)
    except PermissionError:pass
    else:raise AssertionError("approval was not required")
    result=service.send_new_on_server(({"anilist_id":108487,"title":"Fragtime"},),approved=True)
    with sqlite3.connect(profile.database_path) as connection:status=connection.execute("SELECT status FROM manual_announcement_drafts WHERE draft_id=?",(result["draft_id"],)).fetchone()[0]
    assert result["delivered"] and status=="DELIVERED"
