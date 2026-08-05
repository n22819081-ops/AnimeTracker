from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from anime_tracker.gui_qt.application import create_production_application
from anime_tracker.gui_qt.data import AnimeRow, ModernRepository
from anime_tracker.gui_qt.dialogs import AnimeDetailDialog, MatchingReviewDialog
from anime_tracker.modernization.schema_v4 import initialize_matching_test_database
from anime_tracker.production.operations import ProductionInventoryOperations
from anime_tracker.services.matching.candidates import inventory_snapshot_id
from anime_tracker.services.matching.repository import MatchingRepository
from anime_tracker.services.matching.service import MatchingService
from matching_helpers import NOW, inventory_item, media, snapshot
from production_helpers import production_profile


def _row() -> AnimeRow:
    return AnimeRow(
        anilist_id=166216,
        title="The Dangers in My Heart Season 2",
        english="The Dangers in My Heart Season 2",
        romaji="Boku no Kokoro no Yabai Yatsu 2nd Season",
        native="",
        media_format="TV",
        season="WINTER",
        year=2024,
        anilist_status="FINISHED",
        tracker_status="Needs Review",
        server_status="NEEDS_REVIEW",
        coverage="Unknown",
        next_episode="",
        review="Multiple possible matches",
        last_updated="",
    )


def _candidate() -> dict:
    return {
        "candidate_id": "candidate-season-2",
        "display_name": "The Dangers in My Heart (2023)",
        "relative_path": "The Dangers in My Heart (2023)",
        "season_number": 2,
        "confidence": "STRONG",
        "score": 132,
        "evidence_json": "{}",
    }


def test_detail_review_and_franchise_buttons_emit_actions(qtbot):
    row = _row()
    dialog = AnimeDetailDialog(row)
    qtbot.addWidget(dialog)
    reviews = []
    franchises = []
    dialog.review_server_match_requested.connect(reviews.append)
    dialog.view_franchise_requested.connect(franchises.append)

    dialog.action_buttons["Review Server Match"].click()
    dialog.action_buttons["View Franchise"].click()

    assert reviews == [row]
    assert franchises == [row]


def test_confirm_suggestion_emits_exact_candidate_without_closing(qtbot):
    candidate = _candidate()
    review = {"anilist_id": 166216, "title": _row().title, "candidates": (candidate,)}
    dialog = MatchingReviewDialog(review)
    qtbot.addWidget(dialog)
    emitted = []
    dialog.confirm_candidate_requested.connect(lambda selected_review, selected_candidate: emitted.append((selected_review, selected_candidate)))

    dialog.confirm.click()

    assert emitted == [(review, candidate)]
    assert dialog.result() == 0


def test_main_window_confirmation_calls_production_operation_and_refreshes(qtbot, tmp_path):
    profile = production_profile(tmp_path)
    app, window, _ = create_production_application(profile.root)
    qtbot.addWidget(window)
    candidate = _candidate()
    review = {"profile_id": "default", "anilist_id": 166216, "title": _row().title, "candidates": (candidate,)}
    dialog = MatchingReviewDialog(review, window)
    qtbot.addWidget(dialog)

    with patch("anime_tracker.production.operations.ProductionInventoryOperations.confirm_candidate", return_value={"target": candidate["display_name"], "season_number": 2, "server_presence": "COMPLETE"}) as confirm, patch.object(window, "_refresh_pages") as refresh, patch("PySide6.QtWidgets.QMessageBox.information"):
        window._confirm_review_candidate(review, candidate, dialog)

    confirm.assert_called_once_with("candidate-season-2", 166216, profile_id="default")
    refresh.assert_called_once_with()
    assert dialog.result() == 1


def test_persisted_inventory_reconstructs_with_identical_matching_identity(tmp_path):
    profile = production_profile(tmp_path)
    operation = ProductionInventoryOperations(profile)
    original = snapshot(inventory_item("The Dangers in My Heart (2023)", seasons={1: range(1, 13), 2: range(1, 14)}))
    now = datetime.now(timezone.utc)

    operation._persist("snapshot-roundtrip", original, now, now)
    restored = operation.latest_complete_snapshot()

    assert inventory_snapshot_id(restored) == inventory_snapshot_id(original)
    assert restored.items[0].seasons[1].season_number == 2
    assert len(restored.items[0].seasons[1].files) == 13


def test_server_coverage_lists_scanned_unmapped_folders(tmp_path):
    profile = production_profile(tmp_path)
    operation = ProductionInventoryOperations(profile)
    original = snapshot(
        inventory_item("Bakemonogatari (2009)", item_id="bakemonogatari"),
        inventory_item("The Dangers in My Heart (2023)", item_id="dangers", seasons={1: range(1, 13), 2: range(1, 14)}),
    )
    now = datetime.now(timezone.utc)
    operation._persist("snapshot-coverage", original, now, now)

    rows = ModernRepository(profile.database_path).server_folder_rows()

    assert {row["display_name"] for row in rows} == {"Bakemonogatari (2009)", "The Dangers in My Heart (2023)"}
    assert all(row["unmapped"] == "Yes" for row in rows)
    dangers = next(row for row in rows if row["display_name"].startswith("The Dangers"))
    assert dangers["seasons"] == "Season 01, Season 02"


def test_new_candidate_generation_marks_prior_session_candidates_stale(tmp_path):
    database = tmp_path / "matching.db"
    initialize_matching_test_database(database)
    service = MatchingService(MatchingRepository(database), clock=lambda: NOW)
    value = media("Bakemonogatari", anilist_id=5081, year=2009, episodes=15)
    inventory = snapshot(inventory_item("Bakemonogatari (2009)", item_id="bakemonogatari", seasons={1: range(1, 16)}))

    service.generate_candidates(value, inventory, session_id="scan-before")
    service.generate_candidates(value, inventory, session_id="scan-after")

    with sqlite3.connect(database) as connection:
        states = dict(connection.execute("SELECT session_id, MIN(stale) FROM server_match_candidates GROUP BY session_id"))
    assert states == {"scan-before": 1, "scan-after": 0}
