from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .safety import assert_safe_output_path
from .schema_v3 import initialize_anilist_test_database


MODERN_MATCHING_SCHEMA_VERSION = 4

V4_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS matching_sessions (
    session_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    inventory_snapshot_id TEXT NOT NULL,
    anilist_version TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    candidate_count INTEGER NOT NULL DEFAULT 0 CHECK(candidate_count >= 0),
    warning_count INTEGER NOT NULL DEFAULT 0 CHECK(warning_count >= 0),
    canceled INTEGER NOT NULL DEFAULT 0 CHECK(canceled IN (0, 1)),
    partial INTEGER NOT NULL DEFAULT 0 CHECK(partial IN (0, 1))
);

CREATE TABLE IF NOT EXISTS server_match_candidates (
    candidate_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES matching_sessions(session_id) ON DELETE CASCADE,
    profile_id TEXT NOT NULL,
    anilist_id INTEGER NOT NULL CHECK(anilist_id > 0),
    target_identity_key TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK(target_type IN ('SERIES_FOLDER','SERIES_SEASON','SERIES_SPECIALS','MOVIE_ITEM','SEPARATE_SERIES','UNKNOWN_TARGET','NO_SERVER_MAPPING')),
    inventory_item_id TEXT NOT NULL DEFAULT '',
    root_identifier TEXT NOT NULL DEFAULT '',
    relative_path TEXT NOT NULL DEFAULT '',
    normalized_path TEXT NOT NULL DEFAULT '',
    season_number INTEGER CHECK(season_number IS NULL OR season_number >= 0),
    library_kind TEXT NOT NULL CHECK(library_kind IN ('TV','MOVIE','UNKNOWN')),
    content_kind TEXT NOT NULL,
    inventory_snapshot_id TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    path_state TEXT NOT NULL CHECK(path_state IN ('EXISTS','MISSING','UNKNOWN')),
    score INTEGER NOT NULL,
    confidence TEXT NOT NULL CHECK(confidence IN ('VERY_STRONG','STRONG','POSSIBLE','WEAK','CONFLICTING','REJECTED','INSUFFICIENT_EVIDENCE')),
    evidence_json TEXT NOT NULL,
    preselected INTEGER NOT NULL DEFAULT 0 CHECK(preselected IN (0, 1)),
    stale INTEGER NOT NULL DEFAULT 0 CHECK(stale IN (0, 1)),
    suggested_next_action TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE(session_id, target_identity_key)
);

CREATE TABLE IF NOT EXISTS media_server_mappings (
    mapping_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    anilist_id INTEGER NOT NULL CHECK(anilist_id > 0),
    target_identity_key TEXT NOT NULL,
    target_type TEXT NOT NULL CHECK(target_type IN ('SERIES_FOLDER','SERIES_SEASON','SERIES_SPECIALS','MOVIE_ITEM','SEPARATE_SERIES','UNKNOWN_TARGET','NO_SERVER_MAPPING')),
    inventory_item_id TEXT NOT NULL DEFAULT '',
    root_identifier TEXT NOT NULL DEFAULT '',
    relative_path TEXT NOT NULL DEFAULT '',
    normalized_path TEXT NOT NULL DEFAULT '',
    season_number INTEGER CHECK(season_number IS NULL OR season_number >= 0),
    library_kind TEXT NOT NULL CHECK(library_kind IN ('TV','MOVIE','UNKNOWN')),
    content_kind TEXT NOT NULL,
    inventory_snapshot_id TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL DEFAULT '',
    path_state TEXT NOT NULL CHECK(path_state IN ('EXISTS','MISSING','UNKNOWN')),
    evidence_summary_json TEXT NOT NULL DEFAULT '[]',
    mapping_source TEXT NOT NULL,
    confirmation_state TEXT NOT NULL CHECK(confirmation_state IN ('SUGGESTED','CONFIRMED','REJECTED','SUPERSEDED','BROKEN','NEEDS_REVIEW')),
    confidence TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    superseded_at TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
    user_note TEXT NOT NULL DEFAULT '',
    evidence_snapshot_reference TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS mapping_history (
    history_id INTEGER PRIMARY KEY,
    mapping_id TEXT NOT NULL REFERENCES media_server_mappings(mapping_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    state_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rejected_match_decisions (
    rejection_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    anilist_id INTEGER NOT NULL CHECK(anilist_id > 0),
    scope TEXT NOT NULL CHECK(scope IN ('CANDIDATE','EXACT_TARGET','EXACT_PATH','FOLDER','STABLE_INVENTORY_ITEM','SUPPRESS_AUTOMATIC_MATCHING','FRANCHISE')),
    target_identity TEXT NOT NULL,
    target_json TEXT NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    expires_at TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
    cleared_at TEXT,
    source TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS automatic_match_suppressions (
    profile_id TEXT NOT NULL,
    anilist_id INTEGER NOT NULL CHECK(anilist_id > 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
    created_at TEXT NOT NULL,
    cleared_at TEXT,
    reason TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(profile_id, anilist_id)
);

CREATE TABLE IF NOT EXISTS review_cases (
    review_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    anilist_id INTEGER NOT NULL CHECK(anilist_id > 0),
    review_type TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('OPEN','ACKNOWLEDGED','RESOLVED','DISMISSED','SUPERSEDED')),
    severity TEXT NOT NULL CHECK(severity IN ('INFO','WARNING','BLOCKING')),
    evidence_json TEXT NOT NULL DEFAULT '[]',
    related_mapping_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolution TEXT NOT NULL DEFAULT '',
    user_note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS review_case_candidates (
    review_id TEXT NOT NULL REFERENCES review_cases(review_id) ON DELETE CASCADE,
    candidate_id TEXT NOT NULL,
    PRIMARY KEY(review_id, candidate_id)
);

CREATE TABLE IF NOT EXISTS mapping_evidence (
    evidence_id INTEGER PRIMARY KEY,
    mapping_id TEXT NOT NULL REFERENCES media_server_mappings(mapping_id) ON DELETE CASCADE,
    evidence_type TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    inventory_snapshot_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mapping_overrides (
    override_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    anilist_id INTEGER NOT NULL CHECK(anilist_id > 0),
    decision_type TEXT NOT NULL CHECK(decision_type IN ('NOT_ON_SERVER','NO_VALID_CANDIDATE','SKIP_FOR_NOW','CLEAR_CONFIRMED_MAPPING')),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    cleared_at TEXT
);

CREATE TABLE IF NOT EXISTS coverage_mapping_snapshots (
    coverage_id INTEGER PRIMARY KEY,
    mapping_id TEXT NOT NULL REFERENCES media_server_mappings(mapping_id) ON DELETE CASCADE,
    inventory_snapshot_id TEXT NOT NULL,
    server_presence TEXT NOT NULL,
    coverage_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(mapping_id, inventory_snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_matching_sessions_profile ON matching_sessions(profile_id, started_at);
CREATE INDEX IF NOT EXISTS idx_match_candidates_media ON server_match_candidates(profile_id, anilist_id, score DESC);
CREATE INDEX IF NOT EXISTS idx_mappings_media_v4 ON media_server_mappings(profile_id, anilist_id, active);
CREATE INDEX IF NOT EXISTS idx_mappings_target_v4 ON media_server_mappings(profile_id, target_identity_key, active);
CREATE INDEX IF NOT EXISTS idx_rejections_media_v4 ON rejected_match_decisions(profile_id, anilist_id, active);
CREATE INDEX IF NOT EXISTS idx_reviews_media_v4 ON review_cases(profile_id, anilist_id, state);
CREATE INDEX IF NOT EXISTS idx_history_mapping_v4 ON mapping_history(mapping_id, occurred_at);
"""

UPGRADED_TABLES = (
    "media_server_mappings",
    "rejected_match_decisions",
    "match_candidates",
    "review_cases",
)


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _execute_schema(connection: sqlite3.Connection) -> None:
    for statement in V4_TABLES_SQL.split(";"):
        if statement.strip():
            connection.execute(statement)


def _rename_v1_matching_tables(connection: sqlite3.Connection) -> None:
    for table in UPGRADED_TABLES:
        legacy_name = f"legacy_{table}_v1"
        if _table_exists(connection, table) and not _table_exists(connection, legacy_name):
            connection.execute(f"ALTER TABLE [{table}] RENAME TO [{legacy_name}]")


def _copy_legacy_rows(connection: sqlite3.Connection, now: str) -> None:
    if _table_exists(connection, "legacy_media_server_mappings_v1"):
        rows = connection.execute(
            """
            SELECT m.*, t.anilist_id, l.library_kind, l.original_path, l.normalized_path,
                   COALESCE(l.jellyfin_item_id, '') AS jellyfin_item_id, COALESCE(l.title, '') AS title
              FROM legacy_media_server_mappings_v1 m
              JOIN tracked_media t ON t.id=m.tracked_media_id
              JOIN server_library_items l ON l.id=m.library_item_id
             ORDER BY m.id
            """
        ).fetchall()
        target_types = {
            "SERIES": "SERIES_FOLDER",
            "SEASON": "SERIES_SEASON",
            "MOVIE": "MOVIE_ITEM",
            "SPECIAL": "SERIES_SPECIALS",
            "UNSPECIFIED": "UNKNOWN_TARGET",
        }
        for row in rows:
            season = row["season_number"]
            target_type = target_types.get(row["target_kind"], "UNKNOWN_TARGET")
            identity = "|".join((
                row["jellyfin_item_id"] or f"legacy-library:{row['library_item_id']}",
                target_type,
                str(season) if season is not None else "",
                row["normalized_path"],
                row["library_kind"],
            ))
            mapping_id = f"legacy-mapping-{row['id']}"
            created = row["confirmed_at"] or now
            connection.execute(
                """
                INSERT INTO media_server_mappings(
                    mapping_id,profile_id,anilist_id,target_identity_key,target_type,inventory_item_id,
                    normalized_path,relative_path,season_number,library_kind,content_kind,display_name,
                    path_state,mapping_source,confirmation_state,confidence,created_at,updated_at,
                    active,user_note,evidence_snapshot_reference
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    mapping_id, "default", row["anilist_id"], identity, target_type,
                    row["jellyfin_item_id"] or f"legacy-library:{row['library_item_id']}",
                    row["normalized_path"], row["original_path"], season, row["library_kind"],
                    row["target_kind"], row["title"], "UNKNOWN", "LEGACY_IMPORT", "CONFIRMED",
                    "INSUFFICIENT_EVIDENCE", created, created, 1,
                    "Legacy mapping preserved without invented scope." if season is None else "Legacy mapping preserved.",
                    "schema-v1",
                ),
            )
            connection.execute(
                "INSERT INTO mapping_history(mapping_id,event_type,state_json,occurred_at,source) VALUES(?,?,?,?,?)",
                (mapping_id, "LEGACY_IMPORTED", json.dumps({"legacy_id": row["id"]}), created, "LEGACY_IMPORT"),
            )

    if _table_exists(connection, "legacy_rejected_match_decisions_v1"):
        rows = connection.execute(
            """
            SELECT r.*, t.anilist_id FROM legacy_rejected_match_decisions_v1 r
            JOIN tracked_media t ON t.id=r.tracked_media_id ORDER BY r.id
            """
        ).fetchall()
        for row in rows:
            target = row["normalized_path"] or row["original_path"]
            scope = "SUPPRESS_AUTOMATIC_MATCHING" if row["block_auto_match"] else "EXACT_PATH"
            connection.execute(
                """
                INSERT INTO rejected_match_decisions(
                    rejection_id,profile_id,anilist_id,scope,target_identity,target_json,reason,
                    created_at,active,source
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f"legacy-rejection-{row['id']}", "default", row["anilist_id"], scope,
                    target, json.dumps({"normalized_path": target}), row["reason"],
                    row["decided_at"] or now, 1, "LEGACY_IMPORT",
                ),
            )

    if _table_exists(connection, "legacy_match_candidates_v1"):
        rows = connection.execute(
            """
            SELECT c.*, t.anilist_id FROM legacy_match_candidates_v1 c
            JOIN tracked_media t ON t.id=c.tracked_media_id ORDER BY c.id
            """
        ).fetchall()
        if rows:
            # The legacy v1 table can carry two candidates on the same folder (a confident
            # and a possible match). They all collapse into one legacy-import-session and
            # are keyed by legacy||{normalized_path}|{media_kind}, so a second candidate on
            # the same folder hits UNIQUE(session_id, target_identity_key) and aborts the
            # whole re-migration. Keep the strongest per key (highest score, ties broken by
            # earliest id) and preserve the losers in archived_legacy_records for manual
            # review -- nothing is invented, nothing is dropped.
            def _rank(r):
                return (r["score"] if r["score"] is not None else 0, -r["id"])

            best: dict[str, sqlite3.Row] = {}
            for row in rows:
                key = f"legacy||{row['normalized_path']}|{row['media_kind']}"
                current = best.get(key)
                if current is None or _rank(row) > _rank(current):
                    best[key] = row
            keep_ids = {row["id"] for row in best.values()}
            duplicate_count = len(rows) - len(keep_ids)
            connection.execute(
                "INSERT INTO matching_sessions VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("legacy-import-session", "default", "legacy-unknown", "legacy-unknown", now, now, len(keep_ids), duplicate_count, 0, 1),
            )
            for row in rows:
                if row["id"] not in keep_ids:
                    connection.execute(
                        "INSERT INTO archived_legacy_records(source_table, source_key, legacy_anilist_id, reason, payload_json, requires_manual_review, archived_at) "
                        "VALUES(?, ?, ?, ?, ?, 1, ?)",
                        (
                            "match_candidates",
                            f"{row['anilist_id']}|{row['normalized_path']}|{row['media_kind']}",
                            row["anilist_id"],
                            "Duplicate legacy candidate for same folder. Manual review required",
                            json.dumps(dict(row), ensure_ascii=False, sort_keys=True, default=str),
                            now,  # archive time = migration time (matches _archive() in migration.py); original scanned_at is preserved in payload_json
                        ),
                    )
                    continue
                identity = f"legacy||{row['normalized_path']}|{row['media_kind']}"
                evidence = {
                    "legacy_confidence_label": row["confidence_label"],
                    "legacy_score": row["score"],
                    "legacy_reasons_json": row["reasons_json"],
                    "warning": "Legacy score is historical evidence, not a modern score.",
                }
                connection.execute(
                    """
                    INSERT INTO server_match_candidates(
                        candidate_id,session_id,profile_id,anilist_id,target_identity_key,target_type,
                        normalized_path,relative_path,library_kind,content_kind,inventory_snapshot_id,
                        path_state,score,confidence,evidence_json,stale,suggested_next_action,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        f"legacy-candidate-{row['id']}", "legacy-import-session", "default",
                        row["anilist_id"], identity, "UNKNOWN_TARGET", row["normalized_path"],
                        row["original_path"], row["media_kind"] if row["media_kind"] in {"TV", "MOVIE"} else "UNKNOWN",
                        "UNKNOWN", "legacy-unknown", "UNKNOWN", row["score"], "INSUFFICIENT_EVIDENCE",
                        json.dumps(evidence, sort_keys=True), 1, "Regenerate before review", row["scanned_at"] or now,
                    ),
                )

    if _table_exists(connection, "legacy_review_cases_v1"):
        rows = connection.execute(
            """
            SELECT r.*, t.anilist_id FROM legacy_review_cases_v1 r
            LEFT JOIN tracked_media t ON t.id=r.tracked_media_id ORDER BY r.id
            """
        ).fetchall()
        for row in rows:
            if row["anilist_id"] is None:
                continue
            if str(row["reason"] or "").casefold() == "no jellyfin match found":
                continue
            state = row["state"] if row["state"] in {"OPEN", "RESOLVED", "DISMISSED"} else "OPEN"
            if row["review_type"] == "MAPPING_SCOPE":
                review_type = "LEGACY_SEASON_SCOPE_UNKNOWN"
            elif "match" in str(row["reason"] or "").casefold():
                review_type = "AMBIGUOUS_STRONG_CANDIDATES"
            else:
                review_type = "INVENTORY_IDENTITY_CHANGED"
            connection.execute(
                """
                INSERT INTO review_cases(
                    review_id,profile_id,anilist_id,review_type,state,severity,evidence_json,
                    created_at,updated_at,resolution,user_note
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f"legacy-review-{row['id']}", "default", row["anilist_id"],
                    review_type,
                    state, "BLOCKING", json.dumps([row["reason"]]), row["opened_at"],
                    row["resolved_at"] or row["opened_at"], "Legacy review imported" if state != "OPEN" else "", "",
                ),
            )


def migrate_modern_database_to_v4(
    path: Path,
    *,
    live_database_path: Path | None = None,
    protected_roots: tuple[Path, ...] | None = None,
    storage_checker_path: Path | None = None,
) -> None:
    if live_database_path and path.resolve() == live_database_path.resolve():
        raise ValueError("Schema v4 migration refuses to alter the live database.")
    kwargs = {"storage_checker_path": storage_checker_path}
    if protected_roots is not None:
        kwargs["protected_roots"] = protected_roots
    assert_safe_output_path(path, **kwargs)
    if not path.exists():
        raise FileNotFoundError(path)

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        versions = {int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")}
        if 4 in versions:
            connection.rollback()
            return
        if 3 not in versions:
            raise ValueError("Schema v4 migration requires a version 3 modern prototype.")
        now = datetime.now(timezone.utc).isoformat()
        _rename_v1_matching_tables(connection)
        _execute_schema(connection)
        _copy_legacy_rows(connection, now)
        connection.execute(
            "INSERT INTO schema_migrations(version,name,applied_at,checksum) VALUES(4,?,?,?)",
            ("matching_review_v4", now, "embedded-matching-schema-v4"),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_matching_test_database(path: Path) -> None:
    initialize_anilist_test_database(path)
    migrate_modern_database_to_v4(path, protected_roots=())
