from __future__ import annotations

import json
import os
import time
from threading import Thread
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from anime_tracker.gui_qt.dialogs import MatchingReviewDialog
from anime_tracker.gui_qt.covers import CoverImageCache
from anime_tracker.gui_qt.main_window import _operation_summary, _production_refresh
from anime_tracker.gui_qt.matching_presenter import (
    CONFIDENCE_DESCRIPTIONS,
    candidate_target,
    evidence_lines,
    evidence_summary,
)
from anime_tracker.services.anilist.cancellation import CancellationToken
from anime_tracker.services.anilist.rate_limit import cancellable_wait


def _candidate(**overrides):
    value = {
        "candidate_id": "candidate-1",
        "display_name": "The Dangers in My Heart (2023)",
        "relative_path": "The Dangers in My Heart (2023)",
        "season_number": 2,
        "confidence": "STRONG",
        "score": 132,
        "evidence_json": json.dumps({
            "absolute_numbering": False,
            "exact_title_variant": True,
            "matched_title": "The Dangers in My Heart",
            "season_evidence": True,
            "episode_range": [1, 12],
            "expected_episode_count": 13,
            "year_conflict": True,
            "warnings": ["Folder year reflects Season 1."],
        }),
    }
    value.update(overrides)
    return value


def test_event_token_supports_shared_cancellation_protocol():
    token = CancellationToken()
    assert not token.is_cancelled() and not token.wait(0)
    token.cancel()
    assert token.is_cancelled() and token.is_canceled and token.is_set() and token.wait(0)


def test_cover_loading_respects_shared_cancellation_protocol(qtbot, tmp_path):
    cache = CoverImageCache(tmp_path)
    token = CancellationToken(); token.cancel()
    pixmap = cache.request("https://example.invalid/cover.jpg", token)
    assert not pixmap.isNull() and not cache.pending


def test_refresh_all_active_worker_token_supports_interruptible_wait():
    class Operation:
        def __init__(self, profile):
            self.profile = profile

        def preview(self):
            return {"count": 69}

        def refresh(self, *, token, baseline):
            assert baseline is False
            assert token.wait(0) is False
            return {"checked": 69, "succeeded": 69, "failed": 0, "cache_hits": 69, "network_requests": 0, "metadata_changes": 0}

    progress = []
    with patch("anime_tracker.production.operations.ProductionAniListOperations", Operation):
        result = _production_refresh(object(), cancel_event=CancellationToken(), progress=lambda *args: progress.append(args))
    assert result["succeeded"] == 69 and progress[-1][0:2] == (69, 69)


def test_cancellation_interrupts_rate_limit_or_retry_wait():
    token = CancellationToken()
    result = []
    thread = Thread(target=lambda: result.append(cancellable_wait(10, token, time.sleep)))
    started = time.perf_counter(); thread.start(); token.cancel(); thread.join(1)
    assert result == [True] and time.perf_counter() - started < 1


def test_refresh_completion_and_partial_success_summaries():
    complete = _operation_summary("AniList refresh all active", {"checked": 69, "succeeded": 69, "failed": 0, "cache_hits": 69, "network_requests": 0, "metadata_changes": 0})
    partial = _operation_summary("AniList refresh all active", {"checked": 69, "succeeded": 67, "failed": 2, "cache_hits": 60, "network_requests": 9, "metadata_changes": 1})
    assert complete.startswith("AniList refresh complete") and "- 69 titles checked" in complete
    assert partial.startswith("AniList refresh: Partial Success") and "- 2 failed" in partial


def test_human_evidence_omits_irrelevant_false_boolean_and_raw_json():
    candidate = _candidate()
    lines = evidence_lines(candidate)
    summary = evidence_summary(candidate)
    assert "Season 02 exists" in lines and "Episodes 1-12 detected" in lines
    assert "Expected episode count: 13" in lines and "Absolute numbering" not in summary
    assert "{" not in summary and '"absolute_numbering"' not in summary


def test_score_is_labeled_as_points_and_thresholds_are_explained(qtbot):
    dialog = MatchingReviewDialog({"title": "Season 2", "candidates": (_candidate(),)})
    qtbot.addWidget(dialog)
    assert dialog.candidates.horizontalHeaderItem(2).text() == "Match points"
    assert "not a percentage" in dialog.candidates.horizontalHeaderItem(2).toolTip()
    assert set(CONFIDENCE_DESCRIPTIONS) == {"VERY_STRONG", "STRONG", "POSSIBLE", "WEAK", "INSUFFICIENT_EVIDENCE", "CONFLICTING", "REJECTED"}


def test_season_scope_and_explicit_technical_evidence(qtbot):
    candidate = _candidate()
    dialog = MatchingReviewDialog({"title": "The Dangers in My Heart Season 2", "candidates": (candidate,)})
    qtbot.addWidget(dialog)
    assert candidate_target(candidate).endswith("Season 02")
    assert dialog.candidates.item(0, 0).text().endswith("Season 02")
    assert "Season scope: Season 02" in dialog.details.toPlainText()
    assert dialog.technical_details.isHidden()
    dialog.technical_toggle.setChecked(True)
    assert not dialog.technical_details.isHidden() and '"absolute_numbering": false' in dialog.technical_details.toPlainText()


def test_review_resize_does_not_rebuild_model_or_query_database(qtbot):
    candidates = tuple(_candidate(candidate_id=f"candidate-{index}") for index in range(13))
    with patch("anime_tracker.gui_qt.dialogs.evidence_summary", wraps=evidence_summary) as formatter:
        dialog = MatchingReviewDialog({"title": "Season 2", "candidates": candidates})
        qtbot.addWidget(dialog)
        build_calls = formatter.call_count
        started = time.perf_counter()
        for width in range(900, 1200, 10):
            dialog.resize(width, 680)
            qtbot.wait(1)
        elapsed = time.perf_counter() - started
    assert formatter.call_count == build_calls
    assert dialog.candidates.rowCount() == 13 and elapsed < 1.5


def test_acceptance_paths_do_not_contain_integration_side_effects():
    import inspect
    from anime_tracker.gui_qt import main_window

    source = inspect.getsource(main_window._production_refresh) + inspect.getsource(MatchingReviewDialog)
    for forbidden in ("requests.post", "webhook", "Register-ScheduledTask", "Storage Checker", "Remove-Item", "Move-Item"):
        assert forbidden not in source
