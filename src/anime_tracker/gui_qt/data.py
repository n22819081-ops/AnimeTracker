from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class AnimeRow:
    anilist_id: int
    title: str
    romaji: str
    native: str
    media_format: str
    season: str
    year: int | None
    anilist_status: str
    tracker_status: str
    server_status: str
    coverage: str
    next_episode: str
    review: str
    last_updated: str
    cover_url: str = ""
    mapping_label: str = "Not mapped"
    relation_label: str = ""
    archived: bool = False

    @property
    def searchable(self) -> str:
        return " ".join(str(value) for value in self.__dict__.values()).casefold()


class ModernRepository:
    """Read-oriented GUI repository. Widgets never issue SQL."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
        finally:
            connection.close()

    def tracked_media(self, *, include_archived: bool = False) -> tuple[AnimeRow, ...]:
        where = "" if include_archived else "WHERE tm.archived_at IS NULL"
        with self.connect() as connection:
            rows = connection.execute(f"""
                SELECT tm.anilist_id,tm.archived_at,tm.legacy_payload_json,
                       am.media_format,am.season_name,am.season_year,am.anilist_status,
                       am.cover_image_url,am.source_updated_at,
                       ts.tracker_status,ts.server_presence,ts.episode_coverage,
                       ts.review_status,ts.review_reason,
                       (SELECT title FROM media_titles t WHERE t.anilist_id=tm.anilist_id AND t.title_type='ENGLISH' LIMIT 1) english,
                       (SELECT title FROM media_titles t WHERE t.anilist_id=tm.anilist_id AND t.title_type='ROMAJI' LIMIT 1) romaji,
                       (SELECT title FROM media_titles t WHERE t.anilist_id=tm.anilist_id AND t.title_type='NATIVE' LIMIT 1) native,
                       (SELECT target_type || CASE WHEN season_number IS NOT NULL THEN ' · Season ' || printf('%02d',season_number) ELSE '' END
                        FROM media_server_mappings m WHERE m.anilist_id=tm.anilist_id AND m.active=1 LIMIT 1) mapping_label
                  FROM tracked_media tm
                  JOIN anilist_media am ON am.anilist_id=tm.anilist_id
                  LEFT JOIN tracking_state ts ON ts.tracked_media_id=tm.id
                  {where}
                 ORDER BY COALESCE(english,romaji,native),tm.anilist_id
            """).fetchall()
        return tuple(self._row(row) for row in rows)

    def dashboard_counts(self) -> dict[str, int]:
        rows = self.tracked_media()
        return {
            "Currently Airing": sum(row.tracker_status == "Currently Airing" for row in rows),
            "Missing Aired Episodes": sum(row.server_status == "PARTIAL" for row in rows),
            "Finished / Ready to Add": sum("Finished" in row.tracker_status and row.server_status != "COMPLETE" for row in rows),
            "Upcoming This Month": sum(row.tracker_status == "Upcoming" for row in rows),
            "Movies Digitally Available": sum(row.media_format == "MOVIE" and "Digital" in row.tracker_status for row in rows),
            "On Server": sum(row.server_status == "COMPLETE" for row in rows),
            "Needs Review": len(self.review_rows()),
            "Notification Queue Health": self.notification_count("RETRY_WAIT") + self.notification_count("FAILED_PERMANENT"),
        }

    def notification_rows(self) -> tuple[dict, ...]:
        with self.connect() as connection:
            rows = connection.execute("""
                SELECT o.outbox_id,e.event_type,e.anilist_id,o.channel_purpose,o.created_at,o.status,
                       o.attempt_count,o.next_attempt_at,o.last_error_message,o.delivered_at,o.payload_json
                  FROM notification_outbox o JOIN notification_events_v2 e ON e.event_id=o.event_id
                 ORDER BY o.created_at DESC
            """).fetchall()
        return tuple(dict(row) for row in rows)

    def notification_count(self, status: str) -> int:
        with self.connect() as connection:
            return int(connection.execute("SELECT count(*) FROM notification_outbox WHERE status=?", (status,)).fetchone()[0])

    def review_rows(self) -> tuple[dict, ...]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM review_cases WHERE state IN ('OPEN','ACKNOWLEDGED') ORDER BY severity DESC,created_at").fetchall()
        return tuple(dict(row) for row in rows)

    def history_rows(self) -> tuple[dict, ...]:
        with self.connect() as connection:
            mappings = connection.execute("SELECT event_type occurred,occurred_at,mapping_id source FROM mapping_history ORDER BY occurred_at DESC LIMIT 100").fetchall()
        return tuple(dict(row) for row in mappings)

    def import_preview(self) -> dict[str, int]:
        with self.connect() as connection:
            return {
                "active_titles": connection.execute("SELECT count(*) FROM tracked_media WHERE archived_at IS NULL").fetchone()[0],
                "archived_orphans": connection.execute("SELECT count(*) FROM archived_legacy_records").fetchone()[0],
                "baseline_rows": connection.execute("SELECT count(*) FROM shared_announcement_baselines_v2").fetchone()[0],
                "mappings": connection.execute("SELECT count(*) FROM media_server_mappings").fetchone()[0],
                "rejections": connection.execute("SELECT count(*) FROM rejected_match_decisions").fetchone()[0],
                "candidates": connection.execute("SELECT count(*) FROM server_match_candidates").fetchone()[0],
            }

    @staticmethod
    def _row(row: sqlite3.Row) -> AnimeRow:
        payload = json.loads(row["legacy_payload_json"] or "{}")
        title = row["english"] or row["romaji"] or row["native"] or f"AniList {row['anilist_id']}"
        return AnimeRow(
            row["anilist_id"], title, row["romaji"] or "", row["native"] or "",
            row["media_format"] or "UNKNOWN", row["season_name"] or "", row["season_year"],
            row["anilist_status"] or "UNKNOWN", row["tracker_status"] or "Unknown",
            row["server_presence"] or "NOT_FOUND", row["episode_coverage"] or "UNKNOWN",
            str(payload.get("next_airing_episode") or ""), row["review_status"] or "",
            row["source_updated_at"] or "", row["cover_image_url"] or "",
            row["mapping_label"] or "Not mapped", payload.get("relation_label", ""), bool(row["archived_at"]),
        )
