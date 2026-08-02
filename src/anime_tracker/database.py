from __future__ import annotations

import csv
import json
import logging
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Iterable

from .constants import BACKUP_DIR, DATA_DIR, DB_PATH, DEFAULT_MOVIE_PATH, DEFAULT_TV_PATH
from .constants import (
    REVIEW_MULTIPLE_MATCHES,
    REVIEW_NO_MATCH,
    REVIEW_POSSIBLE_MATCHES,
    SERVER_NOT_FOUND,
    SERVER_NOT_ON_SERVER,
    SERVER_ON_SERVER,
    TRACKER_NEEDS_REVIEW,
    TRACKER_ON_SERVER,
    TRACKER_STATUS_PRIORITY,
)
from .models import AnimeRecord
from .announcements import SnapshotItem, captured_at
from .manual_announcements import DuplicateManualAnnouncementError, ManualAnnouncement
from .path_utils import normalize_windows_path
from .scanner import ScoredMatch
from .status import tracker_status_from_anilist

LOGGER = logging.getLogger(__name__)


class Database:
    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def close(self) -> None:
        return None

    def backup(self, reason: str) -> Path | None:
        if not self.path.exists():
            return None
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = BACKUP_DIR / f"anime_tracker-{reason}-{stamp}.db"
        shutil.copy2(self.path, target)
        LOGGER.info("Database backup created at %s", target)
        return target

    def migrate(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS anime (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    english_title TEXT NOT NULL,
                    romaji_title TEXT NOT NULL,
                    native_title TEXT NOT NULL,
                    alternate_titles TEXT NOT NULL DEFAULT '[]',
                    anilist_id INTEGER NOT NULL UNIQUE,
                    format TEXT NOT NULL,
                    season TEXT NOT NULL,
                    year INTEGER,
                    total_episodes INTEGER,
                    airing_status TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    expected_end_date TEXT NOT NULL,
                    cover_image_url TEXT NOT NULL,
                    anilist_url TEXT NOT NULL,
                    tracker_status TEXT NOT NULL,
                    server_status TEXT NOT NULL DEFAULT 'Not Found',
                    detected_server_path TEXT NOT NULL DEFAULT '',
                    date_added TEXT NOT NULL,
                    last_checked TEXT NOT NULL DEFAULT '',
                    previous_status TEXT NOT NULL DEFAULT '',
                    notification_state TEXT NOT NULL DEFAULT '',
                    manual_notes TEXT NOT NULL DEFAULT '',
                    movie_availability TEXT NOT NULL DEFAULT 'unknown'
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notification_events (
                    event_key TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    anilist_id INTEGER,
                    sent_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS server_matches (
                    anilist_id INTEGER PRIMARY KEY,
                    path TEXT NOT NULL,
                    season_label TEXT NOT NULL DEFAULT '',
                    confirmation_type TEXT NOT NULL DEFAULT 'manual',
                    confirmed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rejected_matches (
                    anilist_id INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    rejected_at TEXT NOT NULL,
                    PRIMARY KEY (anilist_id, path)
                );
                CREATE TABLE IF NOT EXISTS match_candidates (
                    anilist_id INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    reasons TEXT NOT NULL,
                    year INTEGER,
                    media_kind TEXT NOT NULL,
                    scanned_at TEXT NOT NULL,
                    PRIMARY KEY (anilist_id, path)
                );
                CREATE TABLE IF NOT EXISTS status_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    anilist_id INTEGER,
                    event TEXT NOT NULL,
                    previous_status TEXT NOT NULL DEFAULT '',
                    new_status TEXT NOT NULL DEFAULT '',
                    server_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jellyfin_announcement_snapshot (
                    item_type TEXT NOT NULL,
                    normalized_path TEXT PRIMARY KEY,
                    parent_normalized_path TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    year INTEGER,
                    season_number INTEGER,
                    original_path TEXT NOT NULL DEFAULT '',
                    captured_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS manual_announcement_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    media_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    normalized_title TEXT NOT NULL,
                    year INTEGER,
                    season_number INTEGER,
                    episodes_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_manual_announcement_duplicate
                    ON manual_announcement_queue(media_type, normalized_title, year, season_number);
                CREATE TABLE IF NOT EXISTS manual_announcement_titles (
                    media_type TEXT NOT NULL,
                    normalized_title TEXT NOT NULL,
                    title TEXT NOT NULL,
                    year INTEGER,
                    last_used_at TEXT NOT NULL,
                    PRIMARY KEY(media_type, normalized_title)
                );
                """
            )
            self._ensure_column(connection, "anime", "movie_availability", "TEXT NOT NULL DEFAULT 'unknown'")
            self._ensure_column(connection, "anime", "api_failure_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "anime", "relation_label", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "anime", "review_reason", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "rejected_matches", "normalized_path", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "rejected_matches", "original_path", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "server_matches", "confirmation_type", "TEXT NOT NULL DEFAULT 'legacy'")
            self._backfill_server_match_confirmation_types(connection)
            connection.execute("CREATE INDEX IF NOT EXISTS idx_rejected_matches_normalized ON rejected_matches(anilist_id, normalized_path)")
            self._backfill_rejected_paths(connection)
            self._ensure_setting(connection, "tv_path", DEFAULT_TV_PATH)
            self._ensure_setting(connection, "movie_path", DEFAULT_MOVIE_PATH)
            self._ensure_setting(connection, "theme", "Dark")
            self._ensure_setting(connection, "schedule_enabled", "false")
            self._ensure_setting(connection, "schedule_frequency", "Weekly")
            self._ensure_setting(connection, "schedule_day", "Sunday")
            self._ensure_setting(connection, "schedule_time", "10:00")
            self._ensure_setting(connection, "schedule_start_when_available", "true")
            self._ensure_setting(connection, "schedule_discord_summary_changes_only", "true")
            self._ensure_setting(connection, "scheduled_last_check", "")
            self._ensure_setting(connection, "scheduled_next_check", "")
            self._ensure_setting(connection, "scheduled_last_result", "Never run")
            self._ensure_setting(connection, "scheduled_titles_updated", "0")
            self._ensure_setting(connection, "scheduled_moved_on_server", "0")
            self._ensure_setting(connection, "scheduled_moved_ready", "0")
            self._ensure_setting(connection, "announcement_baseline_created", "false")

    def has_announcement_baseline(self) -> bool:
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM settings WHERE key='announcement_baseline_created'").fetchone()
            return bool(row and row["value"] == "true")

    def get_announcement_snapshot(self) -> list[SnapshotItem]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT item_type, normalized_path, parent_normalized_path, title, year, season_number, original_path "
                "FROM jellyfin_announcement_snapshot ORDER BY normalized_path"
            ).fetchall()
        return [SnapshotItem(**dict(row)) for row in rows]

    def replace_announcement_snapshot(self, items: Iterable[SnapshotItem]) -> None:
        snapshot = list(items)
        with self.connect() as connection:
            self._replace_announcement_snapshot(connection, snapshot)

    def _replace_announcement_snapshot(self, connection: sqlite3.Connection, snapshot: list[SnapshotItem]) -> None:
        timestamp = captured_at()
        connection.execute("DELETE FROM jellyfin_announcement_snapshot")
        connection.executemany(
                """
                INSERT INTO jellyfin_announcement_snapshot(
                    item_type, normalized_path, parent_normalized_path, title, year,
                    season_number, original_path, captured_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.item_type,
                        item.normalized_path,
                        item.parent_normalized_path,
                        item.title,
                        item.year,
                        item.season_number,
                        item.original_path,
                        timestamp,
                    )
                    for item in snapshot
                ],
        )
        connection.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES('announcement_baseline_created', 'true')"
        )

    def manual_announcements(self) -> list[ManualAnnouncement]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM manual_announcement_queue ORDER BY created_at, id").fetchall()
        return [self._manual_announcement_from_row(row) for row in rows]

    def add_manual_announcement(self, item: ManualAnnouncement) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as connection:
            self._assert_manual_announcement_unique(connection, item)
            cursor = connection.execute(
                """
                INSERT INTO manual_announcement_queue(
                    media_type, title, normalized_title, year, season_number,
                    episodes_json, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (item.media_type, item.title, item.normalized_title, item.year, item.season_number, item.episodes_json, now, now),
            )
            self._remember_manual_title(connection, item, now)
            return int(cursor.lastrowid)

    def update_manual_announcement(self, item_id: int, item: ManualAnnouncement) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as connection:
            existing = connection.execute("SELECT 1 FROM manual_announcement_queue WHERE id=?", (item_id,)).fetchone()
            if not existing:
                raise KeyError(f"Manual announcement {item_id} was not found.")
            self._assert_manual_announcement_unique(connection, item, item_id)
            connection.execute(
                """
                UPDATE manual_announcement_queue
                SET media_type=?, title=?, normalized_title=?, year=?, season_number=?,
                    episodes_json=?, updated_at=?
                WHERE id=?
                """,
                (item.media_type, item.title, item.normalized_title, item.year, item.season_number, item.episodes_json, now, item_id),
            )
            self._remember_manual_title(connection, item, now)

    def manual_title_suggestions(self, media_type: str) -> list[tuple[str, int | None]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT title, year FROM manual_announcement_titles WHERE media_type=? ORDER BY last_used_at DESC, title",
                (media_type,),
            ).fetchall()
        return [(row["title"], row["year"]) for row in rows]

    def delete_manual_announcements(self, item_ids: Iterable[int]) -> None:
        ids = [int(item_id) for item_id in item_ids]
        if not ids:
            return
        with self.connect() as connection:
            connection.executemany("DELETE FROM manual_announcement_queue WHERE id=?", [(item_id,) for item_id in ids])

    def commit_announcement_send(self, snapshot: Iterable[SnapshotItem], manual_queue_ids: Iterable[int]) -> None:
        ids = [int(item_id) for item_id in manual_queue_ids]
        with self.connect() as connection:
            self._replace_announcement_snapshot(connection, list(snapshot))
            if ids:
                connection.executemany("DELETE FROM manual_announcement_queue WHERE id=?", [(item_id,) for item_id in ids])

    def _assert_manual_announcement_unique(
        self,
        connection: sqlite3.Connection,
        item: ManualAnnouncement,
        exclude_id: int | None = None,
    ) -> None:
        rows = connection.execute(
            """
            SELECT id, episodes_json FROM manual_announcement_queue
            WHERE media_type=? AND normalized_title=?
              AND COALESCE(year, -1)=COALESCE(?, -1)
              AND COALESCE(season_number, -1)=COALESCE(?, -1)
            """,
            (item.media_type, item.normalized_title, item.year, item.season_number),
        ).fetchall()
        for row in rows:
            if exclude_id is not None and int(row["id"]) == int(exclude_id):
                continue
            if item.media_type == "MOVIE" or tuple(json.loads(row["episodes_json"] or "[]")) == item.episodes:
                raise DuplicateManualAnnouncementError("An identical announcement is already pending.")

    def _remember_manual_title(self, connection: sqlite3.Connection, item: ManualAnnouncement, timestamp: str) -> None:
        connection.execute(
            """
            INSERT INTO manual_announcement_titles(media_type, normalized_title, title, year, last_used_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(media_type, normalized_title) DO UPDATE SET
                title=excluded.title,
                year=COALESCE(excluded.year, manual_announcement_titles.year),
                last_used_at=excluded.last_used_at
            """,
            (item.media_type, item.normalized_title, item.title, item.year, timestamp),
        )

    def _manual_announcement_from_row(self, row: sqlite3.Row) -> ManualAnnouncement:
        return ManualAnnouncement(
            media_type=row["media_type"],
            title=row["title"],
            year=row["year"],
            season_number=row["season_number"],
            episodes=tuple(json.loads(row["episodes_json"] or "[]")),
            id=row["id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _ensure_column(self, connection: sqlite3.Connection, table: str, name: str, ddl: str) -> None:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if name not in columns:
            self.backup("migration")
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    def _ensure_setting(self, connection: sqlite3.Connection, key: str, value: str) -> None:
        connection.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
            (key, value),
        )

    def _backfill_rejected_paths(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            "SELECT anilist_id, path, normalized_path, original_path FROM rejected_matches WHERE normalized_path='' OR original_path=''"
        ).fetchall()
        for row in rows:
            original = row["original_path"] or row["path"]
            connection.execute(
                "UPDATE rejected_matches SET normalized_path=?, original_path=? WHERE anilist_id=? AND path=?",
                (normalize_windows_path(original), original, row["anilist_id"], row["path"]),
            )

    def _backfill_server_match_confirmation_types(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            UPDATE server_matches
            SET confirmation_type = CASE
                WHEN EXISTS (
                    SELECT 1 FROM anime
                    WHERE anime.anilist_id = server_matches.anilist_id
                      AND anime.server_status = 'On Server - Manual'
                ) THEN 'manual'
                WHEN EXISTS (
                    SELECT 1 FROM status_history
                    WHERE status_history.anilist_id = server_matches.anilist_id
                      AND status_history.server_path = server_matches.path
                      AND status_history.event IN (
                          'Server path confirmed',
                          'Manually selected Jellyfin folder',
                          'Manually marked on server',
                          'Confirmed on server'
                      )
                ) THEN 'manual'
                ELSE 'automatic'
            END
            WHERE confirmation_type = 'legacy'
            """
        )

    def upsert_anime(self, record: AnimeRecord) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id, date_added FROM anime WHERE anilist_id = ?",
                (record.anilist_id,),
            ).fetchone()
            date_added = existing["date_added"] if existing else now
            payload = self._record_values(record, date_added, now)
            if existing:
                payload["id"] = existing["id"]
                connection.execute(
                    """
                    UPDATE anime SET
                        english_title=:english_title, romaji_title=:romaji_title,
                        native_title=:native_title, alternate_titles=:alternate_titles,
                        format=:format, season=:season, year=:year,
                        total_episodes=:total_episodes, airing_status=:airing_status,
                        start_date=:start_date, expected_end_date=:expected_end_date,
                        cover_image_url=:cover_image_url, anilist_url=:anilist_url,
                        tracker_status=:tracker_status, server_status=:server_status,
                        detected_server_path=:detected_server_path, last_checked=:last_checked,
                        previous_status=:previous_status, notification_state=:notification_state,
                        manual_notes=:manual_notes, movie_availability=:movie_availability,
                        relation_label=:relation_label, review_reason=:review_reason
                    WHERE id=:id
                    """,
                    payload,
                )
                return int(existing["id"])
            cursor = connection.execute(
                """
                INSERT INTO anime (
                    english_title, romaji_title, native_title, alternate_titles, anilist_id,
                    format, season, year, total_episodes, airing_status, start_date,
                    expected_end_date, cover_image_url, anilist_url, tracker_status,
                    server_status, detected_server_path, date_added, last_checked,
                    previous_status, notification_state, manual_notes, movie_availability, relation_label, review_reason
                ) VALUES (
                    :english_title, :romaji_title, :native_title, :alternate_titles, :anilist_id,
                    :format, :season, :year, :total_episodes, :airing_status, :start_date,
                    :expected_end_date, :cover_image_url, :anilist_url, :tracker_status,
                    :server_status, :detected_server_path, :date_added, :last_checked,
                    :previous_status, :notification_state, :manual_notes, :movie_availability, :relation_label, :review_reason
                )
                """,
                payload,
            )
            return int(cursor.lastrowid)

    def update_from_anilist(self, row_id: int, record: AnimeRecord, previous_status: str, notification_state: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE anime SET english_title=?, romaji_title=?, native_title=?, alternate_titles=?,
                    format=?, season=?, year=?, total_episodes=?, airing_status=?, start_date=?,
                    expected_end_date=?, cover_image_url=?, anilist_url=?, tracker_status=?,
                    previous_status=?, notification_state=?, last_checked=?, movie_availability=?, relation_label=?
                WHERE id=?
                """,
                (
                    record.english_title,
                    record.romaji_title,
                    record.native_title,
                    json.dumps(record.alternate_titles, ensure_ascii=False),
                    record.format,
                    record.season,
                    record.year,
                    record.total_episodes,
                    record.airing_status,
                    record.start_date,
                    record.expected_end_date,
                    record.cover_image_url,
                    record.anilist_url,
                    record.tracker_status,
                    previous_status,
                    notification_state,
                    datetime.now().isoformat(timespec="seconds"),
                    record.movie_availability,
                    record.relation_label,
                    row_id,
                ),
            )

    def set_server_match(self, row_id: int, server_status: str, tracker_status: str, path: str, notes: str = "") -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE anime SET server_status=?, tracker_status=?, detected_server_path=?, manual_notes=? WHERE id=?",
                (server_status, tracker_status, path, notes, row_id),
            )

    def set_review_state(self, row_id: int, server_status: str, tracker_status: str, review_reason: str, path: str = "", notes: str = "") -> None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM anime WHERE id=?", (row_id,)).fetchone()
            previous = row["tracker_status"] if row else ""
            anilist_id = row["anilist_id"] if row else None
            final_path = path if path else (row["detected_server_path"] if row else "")
            connection.execute(
                "UPDATE anime SET server_status=?, tracker_status=?, detected_server_path=?, manual_notes=?, review_reason=? WHERE id=?",
                (server_status, tracker_status, final_path, notes, review_reason, row_id),
            )
            self._add_history(connection, anilist_id, f"Needs review: {review_reason}", previous, tracker_status, final_path)

    def set_on_server(
        self,
        row_id: int,
        path: str = "",
        server_status: str = SERVER_ON_SERVER,
        notes: str = "",
        event: str = "Confirmed on server",
        confirmation_type: str = "manual",
    ) -> None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM anime WHERE id=?", (row_id,)).fetchone()
            previous = row["tracker_status"] if row else ""
            anilist_id = row["anilist_id"] if row else None
            final_path = path or (row["detected_server_path"] if row else "")
            final_notes = notes or (row["manual_notes"] if row else "")
            connection.execute(
                "UPDATE anime SET server_status=?, tracker_status=?, detected_server_path=?, manual_notes=?, review_reason=? WHERE id=?",
                (server_status, TRACKER_ON_SERVER, final_path, final_notes, "", row_id),
            )
            if anilist_id and final_path:
                self._unreject_match(connection, anilist_id, final_path)
                connection.execute(
                    "INSERT OR REPLACE INTO server_matches(anilist_id, path, season_label, confirmation_type, confirmed_at) VALUES(?, ?, ?, ?, ?)",
                    (anilist_id, final_path, row["relation_label"] or "", confirmation_type, datetime.now().isoformat(timespec="seconds")),
                )
            self._add_history(connection, anilist_id, event, previous, TRACKER_ON_SERVER, final_path)

    def set_needs_review_missing(self, row_id: int, path: str) -> None:
        from .constants import SERVER_MISSING_NEEDS_REVIEW, TRACKER_NEEDS_REVIEW

        with self.connect() as connection:
            row = connection.execute("SELECT * FROM anime WHERE id=?", (row_id,)).fetchone()
            if not row:
                return
            connection.execute(
                "UPDATE anime SET server_status=?, tracker_status=?, detected_server_path=?, review_reason=? WHERE id=?",
                (SERVER_MISSING_NEEDS_REVIEW, TRACKER_NEEDS_REVIEW, path, "Previously confirmed path missing", row_id),
            )
            self._add_history(connection, row["anilist_id"], "Server match later removed or missing", row["tracker_status"], TRACKER_NEEDS_REVIEW, path)

    def mark_not_on_server(self, row_id: int, rejected_path: str | None = None) -> str:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM anime WHERE id=?", (row_id,)).fetchone()
            if not row:
                return ""
            if rejected_path:
                self._reject_match(connection, row["anilist_id"], rejected_path)
            connection.execute("DELETE FROM server_matches WHERE anilist_id=?", (row["anilist_id"],))
            new_status = tracker_status_from_anilist(row["airing_status"], row["format"], row["movie_availability"] or "unknown")
            connection.execute(
                "UPDATE anime SET server_status=?, tracker_status=?, review_reason=? WHERE id=?",
                (SERVER_NOT_ON_SERVER, new_status, "", row_id),
            )
            self._add_history(connection, row["anilist_id"], "Reviewed as not on server", row["tracker_status"], new_status, row["detected_server_path"])
            return new_status

    def mark_no_match_found(self, row_id: int) -> str:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM anime WHERE id=?", (row_id,)).fetchone()
            if not row:
                return ""
            if row["tracker_status"] == TRACKER_ON_SERVER:
                return TRACKER_ON_SERVER
            new_status = row["tracker_status"]
            if row["tracker_status"] == TRACKER_NEEDS_REVIEW and row["review_reason"] in {"", REVIEW_NO_MATCH, REVIEW_POSSIBLE_MATCHES, REVIEW_MULTIPLE_MATCHES}:
                new_status = tracker_status_from_anilist(row["airing_status"], row["format"], row["movie_availability"] or "unknown")
            connection.execute(
                "UPDATE anime SET server_status=?, tracker_status=?, detected_server_path='', review_reason=? WHERE id=?",
                (SERVER_NOT_FOUND, new_status, REVIEW_NO_MATCH, row_id),
            )
            return new_status

    def set_review_reason(self, row_id: int, review_reason: str) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE anime SET review_reason=? WHERE id=?", (review_reason, row_id))

    def add_history(self, anilist_id: int | None, event: str, previous_status: str = "", new_status: str = "", server_path: str = "") -> None:
        with self.connect() as connection:
            self._add_history(connection, anilist_id, event, previous_status, new_status, server_path)

    def _add_history(self, connection: sqlite3.Connection, anilist_id: int | None, event: str, previous_status: str, new_status: str, server_path: str) -> None:
        connection.execute(
            "INSERT INTO status_history(anilist_id, event, previous_status, new_status, server_path, created_at) VALUES(?, ?, ?, ?, ?, ?)",
            (anilist_id, event, previous_status, new_status, server_path, datetime.now().isoformat(timespec="seconds")),
        )

    def save_match_candidates(self, anilist_id: int, candidates: list[ScoredMatch]) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM match_candidates WHERE anilist_id=?", (anilist_id,))
            for candidate in candidates:
                if self._is_rejected(connection, anilist_id, candidate.path):
                    continue
                connection.execute(
                    """
                    INSERT OR REPLACE INTO match_candidates(anilist_id, path, confidence, score, reasons, year, media_kind, scanned_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        anilist_id,
                        candidate.path,
                        candidate.confidence,
                        candidate.score,
                        json.dumps(candidate.reasons),
                        candidate.year,
                        candidate.media_kind,
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )

    def get_match_candidates(self, anilist_id: int) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(connection.execute("SELECT * FROM match_candidates WHERE anilist_id=? ORDER BY score DESC", (anilist_id,)))

    def reject_match(self, anilist_id: int, path: str) -> None:
        with self.connect() as connection:
            self._reject_match(connection, anilist_id, path)

    def _reject_match(self, connection: sqlite3.Connection, anilist_id: int, path: str) -> None:
        normalized = normalize_windows_path(path)
        connection.execute(
            """
            INSERT OR REPLACE INTO rejected_matches(anilist_id, path, normalized_path, original_path, rejected_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            (anilist_id, normalized, normalized, path, datetime.now().isoformat(timespec="seconds")),
        )
        connection.execute(
            "DELETE FROM match_candidates WHERE anilist_id=? AND (path=? OR lower(path)=?)",
            (anilist_id, path, normalized),
        )
        confirmed = connection.execute("SELECT path FROM server_matches WHERE anilist_id=?", (anilist_id,)).fetchone()
        if confirmed and normalize_windows_path(confirmed["path"]) == normalized:
            connection.execute("DELETE FROM server_matches WHERE anilist_id=?", (anilist_id,))
        anime = connection.execute("SELECT * FROM anime WHERE anilist_id=?", (anilist_id,)).fetchone()
        if anime and anime["tracker_status"] == TRACKER_ON_SERVER and normalize_windows_path(anime["detected_server_path"]) == normalized:
            tracker_status = tracker_status_from_anilist(anime["airing_status"], anime["format"], anime["movie_availability"] or "unknown")
            connection.execute(
                "UPDATE anime SET server_status=?, tracker_status=?, review_reason=? WHERE anilist_id=?",
                (SERVER_NOT_FOUND, tracker_status, REVIEW_NO_MATCH, anilist_id),
            )
        self._add_history(connection, anilist_id, "Rejected Jellyfin match candidate", "", "", path)

    def confirm_match(self, row_id: int, path: str) -> None:
        self.set_on_server(row_id, path, SERVER_ON_SERVER, event="Server path confirmed")

    def confirmed_match_for(self, anilist_id: int) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute("SELECT * FROM server_matches WHERE anilist_id=?", (anilist_id,)).fetchone()

    def remove_confirmed_match(self, anilist_id: int, path: str = "") -> None:
        with self.connect() as connection:
            if path:
                normalized = normalize_windows_path(path)
                rows = connection.execute("SELECT path FROM server_matches WHERE anilist_id=?", (anilist_id,)).fetchall()
                for row in rows:
                    if normalize_windows_path(row["path"]) == normalized:
                        connection.execute("DELETE FROM server_matches WHERE anilist_id=?", (anilist_id,))
            else:
                connection.execute("DELETE FROM server_matches WHERE anilist_id=?", (anilist_id,))

    def clear_unsupported_automatic_match(self, row_id: int, path: str) -> str:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM anime WHERE id=?", (row_id,)).fetchone()
            if not row:
                return ""
            connection.execute("DELETE FROM server_matches WHERE anilist_id=?", (row["anilist_id"],))
            tracker_status = tracker_status_from_anilist(row["airing_status"], row["format"], row["movie_availability"] or "unknown")
            connection.execute(
                "UPDATE anime SET server_status=?, tracker_status=?, review_reason=? WHERE id=?",
                (SERVER_NOT_FOUND, tracker_status, REVIEW_NO_MATCH, row_id),
            )
            self._add_history(
                connection,
                row["anilist_id"],
                "Automatic season evidence no longer present",
                row["tracker_status"],
                tracker_status,
                path,
            )
            return tracker_status

    def _is_rejected(self, connection: sqlite3.Connection, anilist_id: int, path: str) -> bool:
        normalized = normalize_windows_path(path)
        return connection.execute(
            "SELECT 1 FROM rejected_matches WHERE anilist_id=? AND (normalized_path=? OR lower(path)=?)",
            (anilist_id, normalized, normalized),
        ).fetchone() is not None

    def rejected_paths_for(self, anilist_id: int) -> set[str]:
        with self.connect() as connection:
            rows = connection.execute("SELECT path, normalized_path, original_path FROM rejected_matches WHERE anilist_id=?", (anilist_id,))
            return {
                normalize_windows_path(row["normalized_path"] or row["original_path"] or row["path"])
                for row in rows
            }

    def _unreject_match(self, connection: sqlite3.Connection, anilist_id: int | None, path: str) -> None:
        if not anilist_id or not path:
            return
        normalized = normalize_windows_path(path)
        connection.execute(
            "DELETE FROM rejected_matches WHERE anilist_id=? AND (normalized_path=? OR lower(path)=?)",
            (anilist_id, normalized, normalized),
        )

    def mark_event_sent(self, event_key: str, event_type: str, anilist_id: int | None) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO notification_events(event_key, event_type, anilist_id, sent_at) VALUES(?, ?, ?, ?)",
                (event_key, event_type, anilist_id, datetime.now().isoformat(timespec="seconds")),
            )

    def event_was_sent(self, event_key: str) -> bool:
        with self.connect() as connection:
            row = connection.execute("SELECT 1 FROM notification_events WHERE event_key=?", (event_key,)).fetchone()
        return row is not None

    def reset_api_failure(self, row_id: int) -> None:
        with self.connect() as connection:
            connection.execute("UPDATE anime SET api_failure_count=0 WHERE id=?", (row_id,))

    def record_api_failure(self, row_id: int) -> int:
        with self.connect() as connection:
            connection.execute("UPDATE anime SET api_failure_count=api_failure_count+1 WHERE id=?", (row_id,))
            row = connection.execute("SELECT api_failure_count FROM anime WHERE id=?", (row_id,)).fetchone()
            return int(row["api_failure_count"]) if row else 0

    def update_manual(self, row_id: int, tracker_status: str, server_status: str, path: str, notes: str, movie_availability: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE anime SET tracker_status=?, server_status=?, detected_server_path=?,
                    manual_notes=?, movie_availability=? WHERE id=?
                """,
                (tracker_status, server_status, path, notes, movie_availability, row_id),
            )

    def delete_anime(self, row_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM anime WHERE id=?", (row_id,))

    def rows(self) -> list[sqlite3.Row]:
        with self.connect() as connection:
            rows = list(connection.execute("SELECT * FROM anime ORDER BY english_title"))
        return sorted(rows, key=lambda row: (TRACKER_STATUS_PRIORITY.get(row["tracker_status"], 99), row["english_title"].lower()))

    def get(self, row_id: int) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute("SELECT * FROM anime WHERE id=?", (row_id,)).fetchone()

    def get_settings(self) -> dict[str, str]:
        with self.connect() as connection:
            return {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM settings")}

    def set_settings(self, settings: dict[str, str]) -> None:
        with self.connect() as connection:
            for key, value in settings.items():
                connection.execute("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (key, value))

    def export_csv(self, path: Path, rows: Iterable[sqlite3.Row] | None = None) -> None:
        selected = list(rows) if rows is not None else self.rows()
        if not selected:
            path.write_text("", encoding="utf-8")
            return
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=selected[0].keys())
            writer.writeheader()
            for row in selected:
                writer.writerow(dict(row))

    def add_sample_data(self) -> None:
        samples = [
            AnimeRecord(
                english_title="Frieren: Beyond Journey's End",
                romaji_title="Sousou no Frieren",
                native_title="葬送のフリーレン",
                alternate_titles=["Frieren"],
                anilist_id=154587,
                format="TV",
                season="FALL",
                year=2023,
                total_episodes=28,
                airing_status="FINISHED",
                start_date="2023-09-29",
                expected_end_date="2024-03-22",
                cover_image_url="",
                anilist_url="https://anilist.co/anime/154587",
                tracker_status="Finished / Ready to Add",
            ),
            AnimeRecord(
                english_title="Sample Upcoming Movie",
                romaji_title="Sample Upcoming Movie",
                native_title="",
                alternate_titles=[],
                anilist_id=999000001,
                format="MOVIE",
                season="",
                year=2027,
                total_episodes=1,
                airing_status="NOT_YET_RELEASED",
                start_date="2027",
                expected_end_date="",
                cover_image_url="",
                anilist_url="https://anilist.co/anime/999000001",
                tracker_status="Movie Theatrical Only",
            ),
        ]
        for sample in samples:
            self.upsert_anime(sample)

    def _record_values(self, record: AnimeRecord, date_added: str, last_checked: str) -> dict:
        return {
            "english_title": record.english_title,
            "romaji_title": record.romaji_title,
            "native_title": record.native_title,
            "alternate_titles": json.dumps(record.alternate_titles, ensure_ascii=False),
            "anilist_id": record.anilist_id,
            "format": record.format,
            "season": record.season,
            "year": record.year,
            "total_episodes": record.total_episodes,
            "airing_status": record.airing_status,
            "start_date": record.start_date,
            "expected_end_date": record.expected_end_date,
            "cover_image_url": record.cover_image_url,
            "anilist_url": record.anilist_url,
            "tracker_status": record.tracker_status,
            "server_status": record.server_status,
            "detected_server_path": record.detected_server_path,
            "date_added": date_added,
            "last_checked": last_checked,
            "previous_status": record.previous_status,
            "notification_state": record.notification_state,
            "manual_notes": record.manual_notes,
            "movie_availability": record.movie_availability,
            "relation_label": record.relation_label,
            "review_reason": "",
        }
