from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .safety import assert_safe_output_path

MODERN_ANILIST_SCHEMA_VERSION = 3

V3_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS anilist_media_cache (
    anilist_id INTEGER PRIMARY KEY CHECK(anilist_id > 0),
    normalized_payload_json TEXT NOT NULL,
    raw_response_json TEXT NOT NULL DEFAULT '',
    retrieved_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_successful_refresh TEXT NOT NULL,
    last_attempted_refresh TEXT NOT NULL,
    last_error_type TEXT NOT NULL DEFAULT '',
    last_error_message TEXT NOT NULL DEFAULT '',
    failure_count INTEGER NOT NULL DEFAULT 0 CHECK(failure_count >= 0),
    stale INTEGER NOT NULL DEFAULT 0 CHECK(stale IN (0, 1)),
    provider_etag TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS anilist_title_variants (
    anilist_id INTEGER NOT NULL REFERENCES anilist_media_cache(anilist_id) ON DELETE CASCADE,
    title_type TEXT NOT NULL CHECK(title_type IN ('primary', 'english', 'romaji', 'native', 'synonym')),
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    PRIMARY KEY(anilist_id, title_type, title)
);

CREATE TABLE IF NOT EXISTS anilist_relations (
    source_anilist_id INTEGER NOT NULL,
    target_anilist_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL,
    target_format TEXT NOT NULL DEFAULT 'UNKNOWN',
    target_status TEXT NOT NULL DEFAULT 'UNKNOWN',
    target_title TEXT NOT NULL DEFAULT '',
    direction TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'AniList',
    retrieved_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY(source_anilist_id, target_anilist_id, relation_type, direction)
);

CREATE TABLE IF NOT EXISTS anilist_relation_state (
    anilist_id INTEGER PRIMARY KEY,
    retrieved_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS anilist_airing_schedule (
    schedule_id INTEGER,
    anilist_id INTEGER NOT NULL,
    episode_number INTEGER NOT NULL CHECK(episode_number > 0),
    airing_at TEXT NOT NULL,
    time_until_airing INTEGER,
    has_aired INTEGER NOT NULL CHECK(has_aired IN (0, 1)),
    retrieved_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY(anilist_id, episode_number)
);

CREATE TABLE IF NOT EXISTS anilist_schedule_state (
    anilist_id INTEGER PRIMARY KEY,
    retrieved_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS anilist_refresh_items (
    id INTEGER PRIMARY KEY,
    batch_key TEXT NOT NULL,
    anilist_id INTEGER NOT NULL,
    success INTEGER NOT NULL CHECK(success IN (0, 1)),
    cache_hit INTEGER NOT NULL CHECK(cache_hit IN (0, 1)),
    network_request_performed INTEGER NOT NULL CHECK(network_request_performed IN (0, 1)),
    canceled INTEGER NOT NULL DEFAULT 0 CHECK(canceled IN (0, 1)),
    stale_cache_used INTEGER NOT NULL DEFAULT 0 CHECK(stale_cache_used IN (0, 1)),
    error_type TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    UNIQUE(batch_key, anilist_id)
);

CREATE TABLE IF NOT EXISTS anilist_request_state (
    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
    request_limit INTEGER,
    remaining_requests INTEGER,
    reset_at TEXT,
    retry_after_seconds REAL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS franchise_graph_nodes (
    anilist_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    media_format TEXT NOT NULL DEFAULT 'UNKNOWN',
    tracked INTEGER NOT NULL DEFAULT 0 CHECK(tracked IN (0, 1)),
    retrieved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS franchise_graph_edges (
    source_anilist_id INTEGER NOT NULL,
    target_anilist_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'AniList',
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY(source_anilist_id, target_anilist_id, relation_type, direction)
);

CREATE TABLE IF NOT EXISTS franchise_group_suggestions (
    group_id TEXT PRIMARY KEY,
    member_ids_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    suggested_main_title TEXT NOT NULL DEFAULT '',
    confidence TEXT NOT NULL,
    manual_confirmation_state TEXT NOT NULL DEFAULT 'UNCONFIRMED',
    warnings_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_anilist_cache_expires ON anilist_media_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_anilist_titles_normalized_v3 ON anilist_title_variants(normalized_title);
CREATE INDEX IF NOT EXISTS idx_airing_time_v3 ON anilist_airing_schedule(airing_at);
CREATE INDEX IF NOT EXISTS idx_refresh_items_batch_v3 ON anilist_refresh_items(batch_key);
CREATE INDEX IF NOT EXISTS idx_graph_edges_target_v3 ON franchise_graph_edges(target_anilist_id);
"""


REFRESH_BATCH_COLUMNS = {
    "batch_key": "TEXT",
    "total_count": "INTEGER NOT NULL DEFAULT 0",
    "cache_hit_count": "INTEGER NOT NULL DEFAULT 0",
    "network_request_count": "INTEGER NOT NULL DEFAULT 0",
    "rate_limit_pause_count": "INTEGER NOT NULL DEFAULT 0",
    "canceled_count": "INTEGER NOT NULL DEFAULT 0",
    "partial_success": "INTEGER NOT NULL DEFAULT 0",
    "error_summary_json": "TEXT NOT NULL DEFAULT '{}'",
}


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info([{table}])")}


def _execute_schema(connection: sqlite3.Connection) -> None:
    for statement in V3_TABLES_SQL.split(";"):
        if statement.strip():
            connection.execute(statement)


def migrate_modern_database_to_v3(
    path: Path,
    *,
    live_database_path: Path | None = None,
    protected_roots: tuple[Path, ...] | None = None,
    storage_checker_path: Path | None = None,
) -> None:
    if live_database_path and path.resolve() == live_database_path.resolve():
        raise ValueError("Schema v3 migration refuses to alter the live database.")
    kwargs = {"storage_checker_path": storage_checker_path}
    if protected_roots is not None:
        kwargs["protected_roots"] = protected_roots
    assert_safe_output_path(path, **kwargs)
    if not path.exists():
        raise FileNotFoundError(path)

    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        versions = {int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")}
        if 1 not in versions:
            raise ValueError("Schema v3 migration requires a version 1 modern prototype.")
        now = datetime.now(timezone.utc).isoformat()
        if 2 not in versions:
            connection.execute(
                "INSERT INTO schema_migrations(version,name,applied_at,checksum) VALUES(2,?,?,?)",
                ("domain_layer_v2_marker", now, "no-persistence-change-v2"),
            )
        _execute_schema(connection)
        existing = _columns(connection, "anilist_refresh_batches")
        for name, definition in REFRESH_BATCH_COLUMNS.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE anilist_refresh_batches ADD COLUMN [{name}] {definition}")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_refresh_batch_key_v3 ON anilist_refresh_batches(batch_key) WHERE batch_key IS NOT NULL"
        )
        if 3 not in versions:
            connection.execute(
                "INSERT INTO schema_migrations(version,name,applied_at,checksum) VALUES(3,?,?,?)",
                ("anilist_service_v3", now, "embedded-anilist-schema-v3"),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_anilist_test_database(path: Path) -> None:
    """Create only the v3 service tables in an isolated test-profile database."""
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY,name TEXT,applied_at TEXT,checksum TEXT)")
        connection.execute(
            "CREATE TABLE anilist_refresh_batches(id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT, requested_count INTEGER NOT NULL DEFAULT 0, success_count INTEGER NOT NULL DEFAULT 0, failure_count INTEGER NOT NULL DEFAULT 0, result TEXT NOT NULL DEFAULT 'RUNNING')"
        )
        _execute_schema(connection)
        existing = _columns(connection, "anilist_refresh_batches")
        for name, definition in REFRESH_BATCH_COLUMNS.items():
            if name not in existing:
                connection.execute(f"ALTER TABLE anilist_refresh_batches ADD COLUMN [{name}] {definition}")
        connection.execute(
            "INSERT INTO schema_migrations VALUES(3,'anilist_test_profile_v3',?,'embedded-anilist-schema-v3')",
            (datetime.now(timezone.utc).isoformat(),),
        )
        connection.commit()
    except Exception:
        connection.close()
        path.unlink(missing_ok=True)
        raise
    finally:
        if path.exists():
            connection.close()
