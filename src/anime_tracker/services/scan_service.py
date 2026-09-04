"""Shared headless scan service.

A headless implementation of the "scan Jellyfin for tracked anime" workflow,
used by the CLI (``cli.py``). The Tk GUI keeps its own loop in
``app.py`` because it interleaves Discord notification dedup
(``event_was_sent``/``mark_event_sent``) and shared-announcement review; the
per-row matching logic below is the same code path it calls
(``scan_roots`` + ``match_record`` + the same status writers), so the two
cannot drift.

:func:`run_server_scan` is notification-agnostic: pass a ``notify`` callable
to receive events (``"server-found"`` / ``"server-missing"``) and it will call
``notify(kind, row, extra)``. The CLI uses this to print "newly found" lines;
a GUI adapter could wire its dedup-aware notifier the same way.

Returns a :class:`ScanSummary` with counts and the per-row decisions so the
caller can render progress, a result table, or a one-line message.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..constants import (
    REVIEW_MULTIPLE_MATCHES,
    REVIEW_POSSIBLE_MATCHES,
    SERVER_NEEDS_REVIEW,
    SERVER_ON_SERVER,
    TRACKER_NEEDS_REVIEW,
    TRACKER_ON_SERVER,
)
from ..database import Database
from ..path_utils import normalize_windows_path
from ..scanner import (
    confirmed_match_has_evidence,
    infer_tracked_seasons,
    match_record,
    multi_season_ids,
    scan_roots,
)

# notify(kind, row, extra) where extra is a dict with event details
NotifyFn = Callable[[str, object, dict], None]


@dataclass
class ScanRowResult:
    row_id: int
    anilist_id: int
    title: str
    action: str = ""  # on_server | needs_review | no_match | kept_confirmed | review_missing
    path: str = ""
    score: int | None = None
    candidates: list = field(default_factory=list)


@dataclass
class ScanSummary:
    total: int = 0
    found: int = 0
    needs_review: int = 0
    no_match: int = 0
    kept_confirmed: int = 0
    review_missing: int = 0
    rows: list[ScanRowResult] = field(default_factory=list)

    @property
    def changed(self) -> int:
        return self.found + self.needs_review + self.no_match + self.review_missing


def run_server_scan(
    db: Database,
    *,
    notify: NotifyFn | None = None,
    backup_label: str = "server-scan",
    only_anilist_ids: tuple[int, ...] | None = None,
) -> ScanSummary:
    """Scan the configured TV/Movie roots and reconcile every tracked anime.

    Mirrors the previous ``AnimeTrackerApp.scan_jellyfin`` behaviour exactly
    (including confirmed-match retention and rejection cleanup) but runs
    headless and returns a summary instead of poking a Tk tree.
    """
    summary = ScanSummary()
    db.backup(backup_label)
    settings = db.get_settings()
    candidates = scan_roots(settings.get("tv_path", ""), settings.get("movie_path", ""))
    rows = db.rows()
    if only_anilist_ids:
        wanted = set(only_anilist_ids)
        rows = [row for row in rows if row["anilist_id"] in wanted]
    season_numbers = infer_tracked_seasons(db.rows())
    multi_ids = multi_season_ids(db.rows())

    for row in rows:
        summary.total += 1
        anilist_id = row["anilist_id"]
        result_entry = ScanRowResult(row_id=row["id"], anilist_id=anilist_id, title=row["english_title"])

        season_number = season_numbers.get(anilist_id)
        rejected_paths = db.rejected_paths_for(anilist_id)
        confirmed = db.confirmed_match_for(anilist_id)
        if confirmed and normalize_windows_path(confirmed["path"]) in rejected_paths:
            db.remove_confirmed_match(anilist_id, confirmed["path"])
            confirmed = None

        if confirmed:
            confirmed_path = Path(confirmed["path"])
            if confirmed_path.exists():
                if confirmed_match_has_evidence(confirmed, candidates, season_number):
                    if row["tracker_status"] != TRACKER_ON_SERVER or row["server_status"] != SERVER_ON_SERVER:
                        db.set_on_server(
                            row["id"], confirmed["path"], SERVER_ON_SERVER, row["manual_notes"],
                            "Confirmed server match retained", confirmed["confirmation_type"],
                        )
                        result_entry.action = "on_server"
                        result_entry.path = confirmed["path"]
                        summary.found += 1
                        summary.rows.append(result_entry)
                    else:
                        result_entry.action = "kept_confirmed"
                        result_entry.path = confirmed["path"]
                        summary.kept_confirmed += 1
                        summary.rows.append(result_entry)
                    continue
                db.clear_unsupported_automatic_match(row["id"], confirmed["path"])
                confirmed = None
            else:
                db.set_needs_review_missing(row["id"], confirmed["path"])
                result_entry.action = "review_missing"
                result_entry.path = confirmed["path"]
                summary.review_missing += 1
                summary.rows.append(result_entry)
                if notify:
                    notify("server-missing", row, {"Previous Path": confirmed["path"]})
                continue

        result = match_record(row, candidates, rejected_paths, season_number, multi_ids)
        db.save_match_candidates(anilist_id, result.candidates)
        result_entry.candidates = list(result.candidates)

        if result.confidence == "confident":
            previous_status = row["tracker_status"]
            db.set_on_server(
                row["id"], result.path, SERVER_ON_SERVER, row["manual_notes"],
                f"{previous_status} -> On Server", "automatic",
            )
            result_entry.action = "on_server"
            result_entry.path = result.path
            result_entry.score = result.candidates[0].score if result.candidates else None
            summary.found += 1
            if notify:
                notify("server-found", row, {"Detected Path": result.path, "Previous Status": previous_status})
        elif result.confidence == "uncertain":
            reason = REVIEW_MULTIPLE_MATCHES if len(result.candidates) > 1 else REVIEW_POSSIBLE_MATCHES
            db.set_review_state(
                row["id"], SERVER_NEEDS_REVIEW, TRACKER_NEEDS_REVIEW, reason,
                row["detected_server_path"], result.notes,
            )
            result_entry.action = "needs_review"
            result_entry.path = result.path
            summary.needs_review += 1
        else:
            db.mark_no_match_found(row["id"])
            result_entry.action = "no_match"
            summary.no_match += 1

        summary.rows.append(result_entry)

    return summary
