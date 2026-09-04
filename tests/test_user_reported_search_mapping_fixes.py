from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime,timezone

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

from anime_tracker.gui_qt.data import AnimeRow,ModernRepository,RelationDisplay
from anime_tracker.gui_qt.dialogs import AddAnimeDialog,ServerFolderDialog
from anime_tracker.gui_qt.pages.core import FranchisePage
from anime_tracker.gui_qt.main_window import _operation_summary
from anime_tracker.production.operations import ProductionAniListOperations,ProductionInventoryOperations
from anime_tracker.services.anilist.errors import AniListErrorType,AniListServiceError
from anime_tracker.services.anilist.models import AniListRefreshResult
from anime_tracker.services.anilist.search import AniListSearch,parse_search_input
from anilist_helpers import NOW,client_for,fixture,page_response
from matching_helpers import media
from production_helpers import production_profile


def test_title_search_omits_unused_optional_filters():
    client,session=client_for([page_response([fixture("media_cases.json")["airing_tv"]])])
    values=AniListSearch(client).search_title("Clockwork")
    assert values and session.calls[0][1]["json"]["variables"]=={"search":"Clockwork","page":1,"perPage":20}


def test_manga_url_has_specific_non_outage_error(qtbot):
    with_error=lambda *_args,**_kwargs:(_ for _ in ()).throw(AniListServiceError(AniListErrorType.INVALID_INPUT,"Anime Tracker supports AniList anime entries; manga URLs cannot be added."))
    dialog=AddAnimeDialog(with_error);qtbot.addWidget(dialog);dialog.query.setText("https://anilist.co/manga/94309/Gamers");dialog.run_search()
    assert parse_search_input
    assert "manga URLs cannot be added" in dialog.status.text()
    assert "temporarily unavailable" not in dialog.status.text()
    assert dialog.query.text().endswith("/Gamers")


def test_search_preview_cache_does_not_track_until_confirmed(tmp_path):
    profile=production_profile(tmp_path);value=media("A New Related Season",anilist_id=990001,year=2026)
    class Service:
        def get_media(self,_anilist_id,token=None):return AniListRefreshResult(990001,True,False,True,value)
    before=ModernRepository(profile.database_path).import_preview()["active_titles"]
    operation=ProductionAniListOperations(profile,Service())
    with sqlite3.connect(profile.database_path) as connection:
        assert connection.execute("SELECT count(*) FROM tracked_media WHERE anilist_id=990001").fetchone()[0]==0
    result=operation.add_tracked_media((990001,))
    assert result["added"]==1 and ModernRepository(profile.database_path).import_preview()["active_titles"]==before+1


def test_manual_inventory_choice_is_season_scoped_and_persistent(tmp_path):
    profile=production_profile(tmp_path);anilist_id=166216
    value=media("The Dangers in My Heart Season 2",anilist_id=anilist_id,year=2024,episodes=13)
    from anime_tracker.services.anilist.cache import AniListCache
    AniListCache(profile.database_path).put_media(value,NOW)
    files=[{"path":fr"I:\TV\Dangers\Season 02\Dangers - S02E{number:02d}.mkv","relative_path":fr"Season 02\Dangers - S02E{number:02d}.mkv","normalized_path":fr"i:\tv\dangers\season 02\dangers - s02e{number:02d}.mkv","size":1,"modified_ns":1,"classification":"EPISODE","season_number":2,"episode_numbers":[number],"special_kind":None,"absolute_episode_numbers":[]} for number in range(1,14)]
    item={"item_id":"filesystem:dangers","root_label":"TV Library","library_kind":"TV","path":r"I:\TV\Dangers","normalized_path":r"i:\tv\dangers","title":"The Dangers in My Heart (2023)","year":2023,"seasons":[{"season_number":1,"path":r"I:\TV\Dangers\Season 01","files":[]},{"season_number":2,"path":r"I:\TV\Dangers\Season 02","files":files}],"specials":[],"movie_files":[],"unrecognized_media":[]}
    roots=[{"label":"TV Library","library_kind":"TV","status":"COMPLETE"}]
    stats={"roots_scanned":1,"directories_seen":3,"files_seen":13,"media_files_seen":13,"files_reused":0,"duplicate_paths_skipped":0}
    with sqlite3.connect(profile.database_path) as connection:
        connection.execute("INSERT INTO inventory_snapshots VALUES(?,?,?,?,?,?,?,?,1)",( "snapshot-manual",NOW.isoformat(),NOW.isoformat(),"COMPLETE",json.dumps(roots),json.dumps(stats),"[]",json.dumps([item])));connection.commit()
    repo=ModernRepository(profile.database_path);choice=next(value for value in repo.server_folder_choices("TV") if value["season_number"]==2)
    result=ProductionInventoryOperations(profile).confirm_manual_target(anilist_id,choice)
    with sqlite3.connect(profile.database_path) as connection:
        mapping=connection.execute("SELECT season_number,target_type,active FROM media_server_mappings WHERE anilist_id=? ORDER BY updated_at DESC LIMIT 1",(anilist_id,)).fetchone()
        state=connection.execute("SELECT ts.tracker_status,ts.server_presence FROM tracking_state ts JOIN tracked_media tm ON tm.id=ts.tracked_media_id WHERE tm.anilist_id=?",(anilist_id,)).fetchone()
        reviews=connection.execute("SELECT count(*) FROM review_cases WHERE anilist_id=? AND state IN ('OPEN','ACKNOWLEDGED')",(anilist_id,)).fetchone()[0]
    assert result["season_number"]==2 and mapping==(2,"SERIES_SEASON",1)
    assert state==("On Server","ON_SERVER") and reviews==0


def test_server_folder_dialog_exposes_exact_discovered_path(qtbot):
    choice={"display_name":"Example","library_kind":"TV","scope_label":"Season 02","year":2026,"path":r"I:\TV\Example","season_number":2}
    dialog=ServerFolderDialog((choice,));qtbot.addWidget(dialog);dialog.table.selectRow(0)
    assert dialog.ok.isEnabled() and dialog.selected_choice()==choice


def test_franchise_page_lists_untracked_related_seasons(qtbot):
    relation=RelationDisplay(200,"Example Season 2","SEQUEL","OUTBOUND","TV","RELEASING")
    row=AnimeRow(100,"Example Season 1","","","TV","SPRING",2025,"FINISHED","On Server","COMPLETE","COMPLETE","","","",relations=(relation,))
    repo=type("Repo",(),{"tracked_media":lambda self:(row,)})()
    page=FranchisePage(repo);qtbot.addWidget(page);parent=page.tree.topLevelItem(0)
    related=next(parent.child(index) for index in range(parent.childCount()) if parent.child(index).text(0)=="Example Season 2")
    page.tree.setCurrentItem(related)
    assert related.text(5)=="Not tracked" and page.add_related.isEnabled()


def test_add_summary_reports_confirmed_tracker_changes():
    summary=_operation_summary("Add related anime",{"added":1,"existing":0,"failed":0})
    assert "1 added" in summary and "No Jellyfin files were modified" in summary
