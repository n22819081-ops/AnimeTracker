from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from anime_tracker.domain.enums import LibraryKind
from anime_tracker.gui_qt.application import create_production_application
from anime_tracker.gui_qt.dialogs import MatchingReviewDialog
from anime_tracker.gui_qt.main_window import _operation_summary
from anime_tracker.production.operations import ProductionInventoryOperations, configured_roots
from anime_tracker.services.matching.repository import MatchingRepository
from anime_tracker.services.matching.service import MatchingService
from anime_tracker.services.server_inventory.models import LibraryRoot
from production_helpers import production_profile


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _empty_review(profile):
    with sqlite3.connect(profile.database_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT r.* FROM review_cases r
             LEFT JOIN review_case_candidates c ON c.review_id=r.review_id
             LEFT JOIN media_server_mappings m ON m.anilist_id=r.anilist_id AND m.active=1
             WHERE r.state IN ('OPEN','ACKNOWLEDGED') AND c.candidate_id IS NULL AND m.mapping_id IS NULL
             ORDER BY r.created_at LIMIT 1
            """
        ).fetchone()
    assert row is not None
    return dict(row)


def test_no_candidate_dialog_hides_blank_candidate_fields_and_connects_action(qtbot):
    review={"review_id":"review-1","profile_id":"default","anilist_id":123,"title":"Example Season 2","tracker_status":"Needs Review","server_status":"NEEDS_REVIEW","review_type":"AMBIGUOUS_STRONG_CANDIDATES","candidates":()}
    dialog=MatchingReviewDialog(review);qtbot.addWidget(dialog)
    emitted=[];dialog.mark_not_on_server_requested.connect(emitted.append)
    assert dialog.candidates.isHidden()
    assert dialog.empty_candidate_message is not None
    assert "No Jellyfin candidate was found" in dialog.empty_candidate_message.text()
    assert dialog.confirm is None and dialog.reject_candidate is None
    assert dialog.mark_not_on_server.isEnabled() and dialog.choose_folder.isEnabled()
    dialog.mark_not_on_server.click()
    assert emitted==[review]


def test_mark_not_on_server_without_candidate_or_mapping_is_atomic_and_idempotent(tmp_path):
    profile=production_profile(tmp_path);review=_empty_review(profile);repo=MatchingRepository(profile.database_path);service=MatchingService(repo)
    before=len(repo.list_reviews("default"));result=service.resolve_review_not_on_server(review["review_id"],review["anilist_id"])
    service.resolve_review_not_on_server(review["review_id"],review["anilist_id"])
    restarted=MatchingRepository(profile.database_path)
    assert result["server_presence"]=="NOT_ON_SERVER"
    assert restarted.active_manual_decision("default",review["anilist_id"]).value=="NOT_ON_SERVER"
    assert len(restarted.list_reviews("default"))==before-1
    with sqlite3.connect(profile.database_path) as connection:
        assert connection.execute("SELECT count(*) FROM mapping_overrides WHERE anilist_id=? AND decision_type='NOT_ON_SERVER'",(review["anilist_id"],)).fetchone()[0]==1
        assert connection.execute("SELECT count(*) FROM status_history WHERE event_type='MANUALLY_MARKED_NOT_ON_SERVER' AND tracked_media_id=(SELECT id FROM tracked_media WHERE anilist_id=?)",(review["anilist_id"],)).fetchone()[0]==1


def test_mark_not_on_server_writes_only_active_profile_and_preserves_unrelated_reviews(tmp_path):
    active=production_profile(tmp_path/"active");wrong=production_profile(tmp_path/"wrong");wrong_before=_sha(wrong.database_path)
    review=_empty_review(active);service=MatchingService(MatchingRepository(active.database_path))
    unrelated_before=len([item for item in service.list_open_reviews(profile_id="default") if item.anilist_id!=review["anilist_id"]])
    service.resolve_review_not_on_server(review["review_id"],review["anilist_id"])
    unrelated_after=len([item for item in service.list_open_reviews(profile_id="default") if item.anilist_id!=review["anilist_id"]])
    assert unrelated_after==unrelated_before and _sha(wrong.database_path)==wrong_before


def test_manual_not_on_server_prevents_weak_candidates_from_reopening_review(tmp_path):
    from matching_helpers import inventory_item,media,snapshot
    profile=production_profile(tmp_path);review=_empty_review(profile);repo=MatchingRepository(profile.database_path);service=MatchingService(repo)
    service.resolve_review_not_on_server(review["review_id"],review["anilist_id"])
    value=media("Different Subtitle",anilist_id=review["anilist_id"],year=2025)
    service.generate_candidates(value,snapshot(inventory_item("Different Subtitle Extra",year=2024)),profile_id="default")
    assert repo.active_manual_decision("default",review["anilist_id"]).value=="NOT_ON_SERVER"
    assert all(item.anilist_id!=review["anilist_id"] for item in repo.list_reviews("default"))


def test_production_scan_uses_configured_roots_persists_and_runs_matching(tmp_path):
    from anime_tracker.services.anilist.cache import AniListCache
    from matching_helpers import media
    profile=production_profile(tmp_path)
    with sqlite3.connect(profile.database_path) as connection:anilist_id=connection.execute("SELECT anilist_id FROM tracked_media WHERE archived_at IS NULL ORDER BY anilist_id LIMIT 1").fetchone()[0]
    AniListCache(profile.database_path).put_media(media("Example",anilist_id=anilist_id),datetime.now(timezone.utc))
    tv=tmp_path/"TV";show=tv/"Example";(show/"Season 01").mkdir(parents=True);media_file=show/"Example.S01E01.mkv";media_file.write_bytes(b"")
    before=media_file.stat().st_mtime_ns
    roots=(LibraryRoot("Test TV",str(tv),LibraryKind.TV),)
    result=ProductionInventoryOperations(profile).scan(confirmed=True,roots=roots,allow_test_roots=True)
    assert result["complete"] and result["item_count"]==1 and result["titles_processed"]==1
    assert result["candidate_suggestions"]>=1 and result["mappings_revalidated"]==0
    assert media_file.stat().st_mtime_ns==before
    with sqlite3.connect(profile.database_path) as connection:
        assert connection.execute("SELECT count(*) FROM inventory_snapshots WHERE snapshot_id=? AND complete=1",(result["snapshot_id"],)).fetchone()[0]==1
        assert connection.execute("SELECT count(*) FROM matching_sessions WHERE started_at>=?",(result["started_at"],)).fetchone()[0]==1


def test_production_window_wording_profile_assertion_and_refresh_after_decision(qtbot,tmp_path):
    profile=production_profile(tmp_path);app,window,_=create_production_application(profile.root);qtbot.addWidget(window)
    assert "Libraries" in window.scan.text() and "test root" not in window.scan.toolTip().casefold()
    review=_empty_review(profile);dialog=MatchingReviewDialog({**review,"title":"Example","candidates":()});qtbot.addWidget(dialog)
    before=len(window.pages["Needs Review"].rows)
    window._mark_review_not_on_server(review,dialog)
    assert len(window.pages["Needs Review"].rows)==before-1 and dialog.result()==1
    window.repository.database_path=tmp_path/"wrong.db"
    try:
        window._assert_active_profile()
    except RuntimeError as exc:
        assert "Active profile mismatch" in str(exc)
    else:
        raise AssertionError("Profile mismatch was not detected")


def test_operation_summaries_report_real_counts():
    refresh=_operation_summary("AniList refresh all active",{"checked":69,"succeeded":69,"failed":0,"cache_hits":69,"network_requests":0,"metadata_changes":0})
    scan=_operation_summary("Read-only production inventory scan",{"item_count":587,"statistics":{"files_seen":12335,"media_files_seen":10843},"candidate_suggestions":13,"mappings_revalidated":1,"review_cases":8})
    assert "69 titles checked" in refresh and "69 cache hits" in refresh and "0 metadata changes" in refresh
    assert "587 library items" in scan and "12335 files" in scan and "13 candidate suggestions" in scan and "0 mappings auto-confirmed" in scan


def test_review_repository_exceptions_are_visible_and_dialog_stays_open(qtbot,tmp_path):
    profile=production_profile(tmp_path);app,window,_=create_production_application(profile.root);qtbot.addWidget(window)
    review=_empty_review(profile);dialog=MatchingReviewDialog({**review,"title":"Example","candidates":()});qtbot.addWidget(dialog)
    with patch("anime_tracker.services.matching.service.MatchingService.resolve_review_not_on_server",side_effect=RuntimeError("database busy")),patch("PySide6.QtWidgets.QMessageBox.warning") as warning:
        window._mark_review_not_on_server(review,dialog)
    assert dialog.result()==0 and "database busy" in dialog.notice.text() and warning.called


def test_acceptance_actions_never_invoke_discord_scheduler_or_media_writes():
    sources="\n".join(path.read_text(encoding="utf-8") for path in (
        Path(__file__).parents[1]/"src"/"anime_tracker"/"production"/"operations.py",
        Path(__file__).parents[1]/"src"/"anime_tracker"/"services"/"matching"/"repository.py",
        Path(__file__).parents[1]/"src"/"anime_tracker"/"gui_qt"/"main_window.py",
    ))
    for forbidden in ("requests.post", "webhook", "Register-ScheduledTask", "Remove-Item", "Move-Item"):
        assert forbidden not in sources
