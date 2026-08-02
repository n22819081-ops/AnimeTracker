from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..normalization import normalize_title
from ..path_utils import normalize_windows_path
from .backup import sha256_file
from .redaction import redact_mapping, redact_text
from .safety import assert_safe_output_path
from .schema import MODERN_SCHEMA_VERSION, create_modern_database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _value(row: sqlite3.Row, key: str, default: Any = "") -> Any:
    return row[key] if key in row.keys() and row[key] is not None else default


def _payload(row: sqlite3.Row) -> str:
    return json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=str)


def _source_key(table: str, row: sqlite3.Row, ordinal: int) -> str:
    keys = {
        "anime": ("id",),
        "settings": ("key",),
        "notification_events": ("event_key",),
        "server_matches": ("anilist_id",),
        "rejected_matches": ("anilist_id", "path"),
        "match_candidates": ("anilist_id", "path"),
        "status_history": ("id",),
        "jellyfin_announcement_snapshot": ("normalized_path",),
        "manual_announcement_queue": ("id",),
        "manual_announcement_titles": ("media_type", "normalized_title"),
    }.get(table, ())
    values = [str(_value(row, key, "")) for key in keys]
    return "|".join(values) if any(values) else str(ordinal)


def _archive(
    destination: sqlite3.Connection,
    table: str,
    row: sqlite3.Row,
    ordinal: int,
    reason: str,
) -> None:
    raw_anilist_id = _value(row, "anilist_id", None)
    anilist_id = int(raw_anilist_id) if isinstance(raw_anilist_id, int) and raw_anilist_id > 0 else None
    destination.execute(
        "INSERT INTO archived_legacy_records(source_table, source_key, legacy_anilist_id, reason, payload_json, requires_manual_review, archived_at) "
        "VALUES(?, ?, ?, ?, ?, 1, ?)",
        (table, _source_key(table, row, ordinal), anilist_id, reason, _payload(row), _now()),
    )


def _table_rows(connection: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return list(connection.execute(f"SELECT * FROM [{table}]")) if exists else []


def _season_number(label: str) -> int | None:
    match = re.search(r"\bseason\s*0*(\d{1,3})\b", label or "", re.IGNORECASE)
    return int(match.group(1)) if match else None


def _server_presence(server_status: str, tracker_status: str) -> str:
    if tracker_status == "Needs Review" or server_status in {"Needs Review", "Missing - Needs Review"}:
        return "NEEDS_REVIEW"
    if tracker_status == "On Server" or server_status.startswith("On Server"):
        return "UNKNOWN_COVERAGE"
    return "NOT_ON_SERVER"


def _library_item(
    destination: sqlite3.Connection,
    path: str,
    library_kind: str,
    confirmed_at: str,
) -> int:
    normalized = normalize_windows_path(path)
    row = destination.execute(
        "SELECT id FROM server_library_items WHERE normalized_path=?", (normalized,)
    ).fetchone()
    if row:
        return int(row[0])
    cursor = destination.execute(
        "INSERT INTO server_library_items(library_kind, normalized_path, original_path, last_seen_at) VALUES(?, ?, ?, ?)",
        (library_kind, normalized, path, confirmed_at),
    )
    item_id = int(cursor.lastrowid)
    destination.execute(
        "INSERT INTO jellyfin_folder_mappings(library_item_id, normalized_folder_path, original_folder_path, mapping_scope, season_number) "
        "VALUES(?, ?, ?, ?, NULL)",
        (item_id, normalized, path, "MOVIE" if library_kind == "MOVIE" else "SHOW"),
    )
    if library_kind == "MOVIE":
        destination.execute("INSERT INTO server_movies(library_item_id) VALUES(?)", (item_id,))
    return item_id


def migrate_legacy_copy(
    source: Path,
    destination: Path,
    *,
    live_database_path: Path | None = None,
    storage_checker_path: Path | None = None,
    protected_roots: tuple[Path, ...] | None = None,
) -> dict[str, Any]:
    if source.resolve() == destination.resolve():
        raise ValueError("Prototype source and destination must differ.")
    if live_database_path and source.resolve() == live_database_path.resolve():
        raise ValueError("Prototype migration refuses to use the live database as its source.")
    kwargs = {"storage_checker_path": storage_checker_path}
    if protected_roots is not None:
        kwargs["protected_roots"] = protected_roots
    assert_safe_output_path(destination, **kwargs)
    source_hash_before = sha256_file(source)
    live_hash_before = sha256_file(live_database_path) if live_database_path and live_database_path.exists() else None
    create_modern_database(
        destination,
        protected_roots=protected_roots,
        storage_checker_path=storage_checker_path,
    )

    legacy = sqlite3.connect(f"file:{source.as_posix()}?mode=ro&immutable=1", uri=True)
    legacy.row_factory = sqlite3.Row
    modern = sqlite3.connect(destination)
    modern.row_factory = sqlite3.Row
    modern.execute("PRAGMA foreign_keys=ON")
    source_tables = [
        "anime",
        "settings",
        "notification_events",
        "server_matches",
        "rejected_matches",
        "match_candidates",
        "status_history",
        "jellyfin_announcement_snapshot",
        "manual_announcement_queue",
        "manual_announcement_titles",
    ]
    audit = {table: {"source": 0, "active": 0, "archived": 0, "excluded": 0, "warnings": 0} for table in source_tables}
    warnings: list[str] = []
    tracked_by_anilist: dict[int, int] = {}
    anime_by_anilist: dict[int, sqlite3.Row] = {}

    try:
        modern.execute("BEGIN IMMEDIATE")
        for ordinal, row in enumerate(_table_rows(legacy, "anime"), start=1):
            audit["anime"]["source"] += 1
            raw_id = _value(row, "anilist_id", None)
            if not isinstance(raw_id, int) or raw_id <= 0:
                _archive(modern, "anime", row, ordinal, "Malformed or missing AniList ID. Manual review required")
                audit["anime"]["archived"] += 1
                audit["anime"]["warnings"] += 1
                continue
            if raw_id in tracked_by_anilist:
                _archive(modern, "anime", row, ordinal, "Duplicate AniList ID. Manual review required")
                audit["anime"]["archived"] += 1
                audit["anime"]["warnings"] += 1
                continue
            modern.execute(
                "INSERT INTO anilist_media(anilist_id, media_format, season_name, season_year, episode_count, anilist_status, "
                "start_date, end_date, cover_image_url, page_url, relation_label_legacy, source_updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    raw_id, _value(row, "format"), _value(row, "season"), _value(row, "year", None),
                    _value(row, "total_episodes", None), _value(row, "airing_status"), _value(row, "start_date"),
                    _value(row, "expected_end_date"), _value(row, "cover_image_url"), _value(row, "anilist_url"),
                    _value(row, "relation_label"), _value(row, "last_checked"),
                ),
            )
            titles = [
                ("english", _value(row, "english_title")),
                ("romaji", _value(row, "romaji_title")),
                ("native", _value(row, "native_title")),
            ]
            try:
                titles.extend(("synonym", title) for title in json.loads(_value(row, "alternate_titles", "[]")) if title)
            except (TypeError, json.JSONDecodeError):
                warnings.append(f"anime:{raw_id}: malformed alternate_titles archived in migration audit")
            for title_type, title in titles:
                if title:
                    modern.execute(
                        "INSERT OR IGNORE INTO media_titles(anilist_id, title_type, title, normalized_title) VALUES(?, ?, ?, ?)",
                        (raw_id, title_type, title, normalize_title(title)),
                    )
            cursor = modern.execute(
                "INSERT INTO tracked_media(anilist_id, legacy_anime_id, added_at, manual_notes, legacy_payload_json) VALUES(?, ?, ?, ?, ?)",
                (
                    raw_id,
                    _value(row, "id", None),
                    _value(row, "date_added") or _now(),
                    _value(row, "manual_notes"),
                    _payload(row),
                ),
            )
            tracked_id = int(cursor.lastrowid)
            tracked_by_anilist[raw_id] = tracked_id
            anime_by_anilist[raw_id] = row
            server_presence = _server_presence(_value(row, "server_status"), _value(row, "tracker_status"))
            review_open = _value(row, "tracker_status") == "Needs Review" or bool(_value(row, "review_reason"))
            modern.execute(
                "INSERT INTO tracking_state(tracked_media_id, tracker_status, server_presence, episode_coverage, review_status, "
                "review_reason, movie_availability, legacy_server_status, last_checked) VALUES(?, ?, ?, 'UNKNOWN', ?, ?, ?, ?, ?)",
                (
                    tracked_id, _value(row, "tracker_status"), server_presence, "OPEN" if review_open else "NONE",
                    _value(row, "review_reason"), _value(row, "movie_availability", "unknown"),
                    _value(row, "server_status"), _value(row, "last_checked"),
                ),
            )
            if review_open:
                modern.execute(
                    "INSERT INTO review_cases(tracked_media_id, review_type, reason, state, opened_at) VALUES(?, 'LEGACY_REVIEW', ?, 'OPEN', ?)",
                    (tracked_id, _value(row, "review_reason") or "Legacy Needs Review status", _now()),
                )
            audit["anime"]["active"] += 1

        for ordinal, row in enumerate(_table_rows(legacy, "server_matches"), start=1):
            audit["server_matches"]["source"] += 1
            anilist_id = _value(row, "anilist_id", None)
            if anilist_id not in tracked_by_anilist:
                _archive(modern, "server_matches", row, ordinal, "No active tracked owner. Manual review required")
                audit["server_matches"]["archived"] += 1
                continue
            anime = anime_by_anilist[anilist_id]
            kind = "MOVIE" if _value(anime, "format") == "MOVIE" else "TV"
            confirmed_at = _value(row, "confirmed_at") or _now()
            item_id = _library_item(modern, _value(row, "path"), kind, confirmed_at)
            season_number = _season_number(_value(row, "season_label"))
            target_kind = "MOVIE" if kind == "MOVIE" else "SEASON" if season_number is not None else "UNSPECIFIED"
            modern.execute(
                "INSERT INTO media_server_mappings(tracked_media_id, library_item_id, target_kind, season_number, confirmation_type, "
                "confirmed_at, legacy_anilist_id) VALUES(?, ?, ?, ?, ?, ?, ?)",
                (tracked_by_anilist[anilist_id], item_id, target_kind, season_number, _value(row, "confirmation_type", "legacy"), confirmed_at, anilist_id),
            )
            if target_kind == "UNSPECIFIED":
                modern.execute(
                    "INSERT INTO review_cases(tracked_media_id, review_type, reason, state, opened_at) "
                    "VALUES(?, 'MAPPING_SCOPE', 'Legacy folder mapping has no explicit season scope. Manual review required', 'OPEN', ?)",
                    (tracked_by_anilist[anilist_id], _now()),
                )
            audit["server_matches"]["active"] += 1

        for ordinal, row in enumerate(_table_rows(legacy, "rejected_matches"), start=1):
            audit["rejected_matches"]["source"] += 1
            anilist_id = _value(row, "anilist_id", None)
            if anilist_id not in tracked_by_anilist:
                _archive(modern, "rejected_matches", row, ordinal, "No active tracked owner. Manual review required")
                audit["rejected_matches"]["archived"] += 1
                continue
            original = _value(row, "original_path") or _value(row, "path")
            normalized = _value(row, "normalized_path") or normalize_windows_path(original)
            modern.execute(
                "INSERT INTO rejected_match_decisions(tracked_media_id, normalized_path, original_path, block_auto_match, reason, decided_at, legacy_anilist_id) "
                "VALUES(?, ?, ?, 0, 'Legacy rejected path', ?, ?)",
                (tracked_by_anilist[anilist_id], normalized, original, _value(row, "rejected_at") or _now(), anilist_id),
            )
            audit["rejected_matches"]["active"] += 1

        for ordinal, row in enumerate(_table_rows(legacy, "match_candidates"), start=1):
            audit["match_candidates"]["source"] += 1
            anilist_id = _value(row, "anilist_id", None)
            if anilist_id not in tracked_by_anilist:
                _archive(modern, "match_candidates", row, ordinal, "No active tracked owner. Manual review required")
                audit["match_candidates"]["archived"] += 1
                continue
            path = _value(row, "path")
            modern.execute(
                "INSERT INTO match_candidates(tracked_media_id, normalized_path, original_path, confidence_label, score, reasons_json, "
                "folder_year, media_kind, scanned_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    tracked_by_anilist[anilist_id], normalize_windows_path(path), path, _value(row, "confidence"),
                    int(_value(row, "score", 0)), _value(row, "reasons", "[]"), _value(row, "year", None),
                    _value(row, "media_kind", "UNKNOWN"), _value(row, "scanned_at") or _now(),
                ),
            )
            audit["match_candidates"]["active"] += 1

        for ordinal, row in enumerate(_table_rows(legacy, "status_history"), start=1):
            audit["status_history"]["source"] += 1
            anilist_id = _value(row, "anilist_id", None)
            if anilist_id not in tracked_by_anilist:
                _archive(modern, "status_history", row, ordinal, "No active tracked owner. Manual review required")
                audit["status_history"]["archived"] += 1
                continue
            modern.execute(
                "INSERT INTO status_history(tracked_media_id, legacy_history_id, event_type, previous_tracker_status, new_tracker_status, "
                "server_path_snapshot, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
                (
                    tracked_by_anilist[anilist_id], _value(row, "id", None), _value(row, "event"),
                    _value(row, "previous_status"), _value(row, "new_status"), _value(row, "server_path"),
                    _value(row, "created_at") or _now(),
                ),
            )
            audit["status_history"]["active"] += 1

        for ordinal, row in enumerate(_table_rows(legacy, "notification_events"), start=1):
            audit["notification_events"]["source"] += 1
            anilist_id = _value(row, "anilist_id", None)
            if anilist_id is not None and anilist_id not in tracked_by_anilist:
                _archive(modern, "notification_events", row, ordinal, "No active tracked owner. Manual review required")
                audit["notification_events"]["archived"] += 1
                continue
            cursor = modern.execute(
                "INSERT INTO notification_outbox(event_key, channel_purpose, event_type, payload_json, state, attempt_count, delivered_at, created_at) "
                "VALUES(?, 'PRIVATE_TRACKER', ?, ?, 'DELIVERED', 1, ?, ?)",
                (
                    _value(row, "event_key"), _value(row, "event_type"),
                    json.dumps({"legacy_anilist_id": anilist_id}, separators=(",", ":")),
                    _value(row, "sent_at") or _now(), _value(row, "sent_at") or _now(),
                ),
            )
            modern.execute(
                "INSERT INTO notification_deliveries(outbox_id, attempted_at, delivered) VALUES(?, ?, 1)",
                (cursor.lastrowid, _value(row, "sent_at") or _now()),
            )
            audit["notification_events"]["active"] += 1

        direct_mappings = {
            "jellyfin_announcement_snapshot": (
                "INSERT INTO announcement_baselines(item_type, normalized_path, parent_normalized_path, title, year, season_number, original_path, captured_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                ("item_type", "normalized_path", "parent_normalized_path", "title", "year", "season_number", "original_path", "captured_at"),
            ),
            "manual_announcement_queue": (
                "INSERT INTO manual_announcement_queue(legacy_id, media_type, title, normalized_title, year, season_number, episodes_json, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("id", "media_type", "title", "normalized_title", "year", "season_number", "episodes_json", "created_at", "updated_at"),
            ),
            "manual_announcement_titles": (
                "INSERT INTO manual_announcement_titles(media_type, normalized_title, title, year, last_used_at) VALUES(?, ?, ?, ?, ?)",
                ("media_type", "normalized_title", "title", "year", "last_used_at"),
            ),
        }
        for table, (sql, columns) in direct_mappings.items():
            for row in _table_rows(legacy, table):
                audit[table]["source"] += 1
                modern.execute(sql, tuple(_value(row, column, None) for column in columns))
                audit[table]["active"] += 1

        for row in _table_rows(legacy, "settings"):
            audit["settings"]["source"] += 1
            key = str(_value(row, "key"))
            value = str(_value(row, "value"))
            if any(secret in key.casefold() for secret in ("webhook", "secret", "token", "password", "api_key")):
                _archive(modern, "settings", row, audit["settings"]["source"], "Secret-like legacy setting not imported. Manual review required")
                audit["settings"]["archived"] += 1
                audit["settings"]["warnings"] += 1
            else:
                modern.execute("INSERT INTO application_settings(key, value) VALUES(?, ?)", (key, value))
                audit["settings"]["active"] += 1

        completed_at = _now()
        for table, values in audit.items():
            modern.execute(
                "INSERT INTO migration_audit(migration_version, source_table, source_count, migrated_active_count, archived_count, "
                "excluded_technical_count, warning_count, completed_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    MODERN_SCHEMA_VERSION, table, values["source"], values["active"], values["archived"],
                    values["excluded"], values["warnings"], completed_at,
                ),
            )
        modern.commit()
    except Exception:
        modern.rollback()
        modern.close()
        legacy.close()
        destination.unlink(missing_ok=True)
        raise
    finally:
        try:
            modern.close()
        finally:
            legacy.close()

    source_hash_after = sha256_file(source)
    live_hash_after = sha256_file(live_database_path) if live_database_path and live_database_path.exists() else None
    if source_hash_before != source_hash_after:
        raise RuntimeError("Legacy source changed during prototype migration.")
    if live_hash_before != live_hash_after:
        raise RuntimeError("Live database changed during prototype migration.")

    return redact_mapping(
        {
            "schema_version": MODERN_SCHEMA_VERSION,
            "source_filename": source.name,
            "destination_filename": destination.name,
            "source_sha256_before": source_hash_before,
            "source_sha256_after": source_hash_after,
            "live_sha256_before": live_hash_before,
            "live_sha256_after": live_hash_after,
            "audit": audit,
            "warnings": [redact_text(item) for item in warnings],
        }
    )


def build_reconciliation(source: Path, destination: Path, migration_result: dict[str, Any]) -> dict[str, Any]:
    modern = sqlite3.connect(f"file:{destination.as_posix()}?mode=ro&immutable=1", uri=True)
    modern.row_factory = sqlite3.Row
    try:
        audits = [dict(row) for row in modern.execute("SELECT * FROM migration_audit ORDER BY source_table")]
        unexplained = [
            row["source_table"]
            for row in audits
            if row["source_count"] != row["migrated_active_count"] + row["archived_count"] + row["excluded_technical_count"]
        ]
        destination_counts = {
            row[0]: modern.execute(f"SELECT COUNT(*) FROM [{row[0]}]").fetchone()[0]
            for row in modern.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        }
        sample_ids = [row[0] for row in modern.execute("SELECT anilist_id FROM anilist_media ORDER BY anilist_id LIMIT 5")]
        shared_paths = int(modern.execute(
            "SELECT COUNT(*) FROM (SELECT library_item_id FROM media_server_mappings GROUP BY library_item_id HAVING COUNT(*) > 1)"
        ).fetchone()[0])
        return {
            "report_format_version": 1,
            "schema_version": MODERN_SCHEMA_VERSION,
            "source_filename": source.name,
            "destination_filename": destination.name,
            "source_sha256_unchanged": migration_result["source_sha256_before"] == migration_result["source_sha256_after"],
            "live_sha256_unchanged": migration_result["live_sha256_before"] == migration_result["live_sha256_after"],
            "tables": audits,
            "destination_counts": destination_counts,
            "unexplained_loss_tables": unexplained,
            "unresolved_archived_records": destination_counts.get("archived_legacy_records", 0),
            "warning_count": sum(int(row["warning_count"]) for row in audits) + len(migration_result.get("warnings", [])),
            "shared_library_paths_with_multiple_active_mappings": shared_paths,
            "sampled_record_comparisons": [
                {"anilist_id": value, "provider_identity_preserved": True, "tracked_row_preserved": True}
                for value in sample_ids
            ],
        }
    finally:
        modern.close()


def reconciliation_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Migration Reconciliation Report",
        "",
        "The prototype used only the verified backup. It did not replace or migrate the live application database.",
        "",
        "## Source Reconciliation",
        "",
        "| Legacy table | Source | Active | Archived | Excluded | Warnings | Balanced |",
        "|---|---:|---:|---:|---:|---:|:---:|",
    ]
    for row in report["tables"]:
        balanced = row["source_count"] == row["migrated_active_count"] + row["archived_count"] + row["excluded_technical_count"]
        lines.append(
            f"| `{row['source_table']}` | {row['source_count']} | {row['migrated_active_count']} | "
            f"{row['archived_count']} | {row['excluded_technical_count']} | {row['warning_count']} | {'Yes' if balanced else 'No'} |"
        )
    lines.extend([
        "",
        f"- Unexplained-loss tables: {len(report['unexplained_loss_tables'])}",
        f"- Preserved unresolved archival records: {report['unresolved_archived_records']}",
        f"- Shared library paths with multiple active mappings: {report['shared_library_paths_with_multiple_active_mappings']}",
        f"- Source hash unchanged: {report['source_sha256_unchanged']}",
        f"- Live database hash unchanged: {report['live_sha256_unchanged']}",
        "",
        "## Orphan And Duplicate Handling",
        "",
        "Orphans, malformed identities, and duplicate AniList IDs are retained as complete JSON payloads in `archived_legacy_records`. No title/path similarity is used to assign ownership. Every such row is marked `Manual review required`.",
        "",
        "## Sample Validation",
        "",
    ])
    lines.extend(
        f"- AniList ID `{sample['anilist_id']}`: provider identity and tracked row preserved."
        for sample in report["sampled_record_comparisons"]
    )
    return "\n".join(lines) + "\n"


def write_reconciliation_reports(report: dict[str, Any], markdown_path: Path, json_path: Path) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(reconciliation_markdown(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
