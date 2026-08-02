from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .safety import assert_safe_output_path
from .schema_v4 import initialize_matching_test_database


MODERN_NOTIFICATION_SCHEMA_VERSION = 5

RENAMES = {
    "notification_outbox": "legacy_notification_outbox_v1",
    "notification_deliveries": "legacy_notification_deliveries_v1",
    "announcement_baselines": "legacy_announcement_baselines_v1",
    "manual_announcement_queue": "legacy_manual_announcement_queue_v1",
    "manual_announcement_titles": "legacy_manual_announcement_titles_v1",
    "credential_references": "legacy_credential_references_v1",
}

SCHEMA = """
CREATE TABLE notification_events_v2 (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    anilist_id INTEGER,
    franchise_id TEXT NOT NULL DEFAULT '',
    event_timestamp TEXT NOT NULL,
    source_transition_id TEXT NOT NULL DEFAULT '',
    previous_state TEXT NOT NULL DEFAULT '',
    new_state TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('INFO','WARNING','ERROR')),
    privacy_level TEXT NOT NULL CHECK(privacy_level IN ('PRIVATE','SHARED_SAFE')),
    deduplication_key TEXT NOT NULL UNIQUE,
    correlation_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE notification_outbox (
    outbox_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES notification_events_v2(event_id),
    channel_purpose TEXT NOT NULL CHECK(channel_purpose IN ('PRIVATE_TRACKER','SHARED_ANNOUNCEMENT','WINDOWS_LOCAL')),
    credential_reference TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('PENDING','CLAIMED','DELIVERED','RETRY_WAIT','FAILED_PERMANENT','CANCELED','SUPPRESSED','EXPIRED')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    next_attempt_at TEXT,
    claimed_by TEXT NOT NULL DEFAULT '',
    claim_expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_error_type TEXT NOT NULL DEFAULT '',
    last_error_message TEXT NOT NULL DEFAULT '',
    delivered_at TEXT,
    deduplication_key TEXT NOT NULL UNIQUE,
    suppression_reason TEXT NOT NULL DEFAULT ''
);

CREATE TABLE notification_delivery_attempts (
    attempt_id TEXT PRIMARY KEY,
    outbox_id TEXT NOT NULL REFERENCES notification_outbox(outbox_id),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    result TEXT NOT NULL CHECK(result IN ('DELIVERED','RETRYABLE_FAILURE','PERMANENT_FAILURE','CANCELED')),
    http_status INTEGER,
    retryable INTEGER NOT NULL CHECK(retryable IN (0,1)),
    error_type TEXT NOT NULL DEFAULT '',
    error_summary TEXT NOT NULL DEFAULT '',
    response_metadata_json TEXT NOT NULL DEFAULT '{}',
    worker_identity TEXT NOT NULL
);

CREATE TABLE notification_channel_settings (
    profile_id TEXT NOT NULL,
    channel_purpose TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
    credential_reference TEXT NOT NULL DEFAULT '',
    silent INTEGER NOT NULL DEFAULT 0 CHECK(silent IN (0,1)),
    rate_limit_per_minute INTEGER NOT NULL DEFAULT 20,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(profile_id,channel_purpose)
);

CREATE TABLE notification_event_filters (
    profile_id TEXT NOT NULL,
    channel_purpose TEXT NOT NULL,
    event_type TEXT NOT NULL,
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    PRIMARY KEY(profile_id,channel_purpose,event_type)
);

CREATE TABLE notification_templates (
    template_key TEXT NOT NULL,
    version INTEGER NOT NULL,
    channel_purpose TEXT NOT NULL,
    event_type TEXT NOT NULL,
    title_template TEXT NOT NULL,
    body_template TEXT NOT NULL,
    field_definitions_json TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
    PRIMARY KEY(template_key,version)
);

CREATE TABLE notification_suppressions (
    suppression_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL,
    anilist_id INTEGER,
    event_type TEXT,
    channel_purpose TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    ends_at TEXT,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    reason TEXT NOT NULL DEFAULT '',
    cleared_at TEXT
);

CREATE TABLE notification_summary_runs (
    summary_run_id TEXT PRIMARY KEY,
    week_start TEXT NOT NULL,
    channel_purpose TEXT NOT NULL,
    summary_type TEXT NOT NULL,
    status TEXT NOT NULL,
    deduplication_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE notification_summary_items (
    summary_run_id TEXT NOT NULL REFERENCES notification_summary_runs(summary_run_id),
    ordinal INTEGER NOT NULL,
    section_key TEXT NOT NULL,
    item_json TEXT NOT NULL,
    PRIMARY KEY(summary_run_id,ordinal)
);

CREATE TABLE shared_announcement_baselines_v2 (
    baseline_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL DEFAULT 'default',
    inventory_identity TEXT NOT NULL,
    item_type TEXT NOT NULL,
    parent_identity TEXT NOT NULL DEFAULT '',
    display_title TEXT NOT NULL,
    year INTEGER,
    season_number INTEGER,
    evidence_json TEXT NOT NULL DEFAULT '{}',
    accepted_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
    legacy_source INTEGER NOT NULL DEFAULT 0 CHECK(legacy_source IN (0,1)),
    UNIQUE(profile_id,inventory_identity)
);

CREATE TABLE shared_announcement_deliveries (
    delivery_id TEXT PRIMARY KEY,
    outbox_id TEXT NOT NULL REFERENCES notification_outbox(outbox_id),
    baseline_identity TEXT NOT NULL,
    delivered_at TEXT NOT NULL,
    UNIQUE(outbox_id,baseline_identity)
);

CREATE TABLE credential_references (
    reference_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL DEFAULT 'default',
    channel_purpose TEXT NOT NULL,
    provider TEXT NOT NULL CHECK(provider IN ('WINDOWS_CREDENTIAL_MANAGER','WINDOWS_DPAPI','LEGACY_IMPORT_PENDING','TEST_ONLY')),
    credential_identifier TEXT NOT NULL UNIQUE,
    secret_present INTEGER NOT NULL DEFAULT 0 CHECK(secret_present IN (0,1)),
    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE manual_announcement_drafts (
    draft_id TEXT PRIMARY KEY,
    legacy_id INTEGER,
    profile_id TEXT NOT NULL DEFAULT 'default',
    title TEXT NOT NULL,
    grouped_items_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('DRAFT','PENDING','CLAIMED','DELIVERED','FAILED','CANCELED')),
    deduplication_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    delivered_at TEXT
);

CREATE INDEX idx_notification_outbox_claim ON notification_outbox(status,next_attempt_at,claim_expires_at,created_at);
CREATE INDEX idx_notification_attempts_outbox ON notification_delivery_attempts(outbox_id,started_at);
CREATE INDEX idx_notification_suppressions_lookup ON notification_suppressions(profile_id,channel_purpose,anilist_id,event_type,active);
CREATE INDEX idx_shared_baseline_active ON shared_announcement_baselines_v2(profile_id,active,item_type);
"""


def migrate_modern_database_to_v5(
    path: Path,
    *,
    live_database_path: Path | None = None,
    protected_roots: tuple[Path, ...] | None = None,
    storage_checker_path: Path | None = None,
) -> None:
    if live_database_path and path.resolve() == live_database_path.resolve():
        raise ValueError("Schema v5 migration refuses to alter the live database.")
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
        if MODERN_NOTIFICATION_SCHEMA_VERSION in versions:
            connection.rollback()
            return
        if 4 not in versions:
            raise ValueError("Schema v5 migration requires a version 4 modern prototype.")
        for source, destination in RENAMES.items():
            if _table_exists(connection, source) and not _table_exists(connection, destination):
                connection.execute(f"ALTER TABLE {source} RENAME TO {destination}")
        for statement in SCHEMA.split(";"):
            if statement.strip():
                connection.execute(statement)
        now = datetime.now(timezone.utc).isoformat()
        _copy_baseline(connection, now)
        _copy_legacy_outbox(connection, now)
        _copy_manual_queue(connection, now)
        connection.execute(
            "INSERT INTO schema_migrations(version,name,applied_at,checksum) VALUES(5,?,?,?)",
            ("notification_outbox_v5",now,"embedded-notification-schema-v5"),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_notification_test_database(path: Path) -> None:
    initialize_matching_test_database(path)
    migrate_modern_database_to_v5(path, protected_roots=())


def _copy_baseline(connection: sqlite3.Connection, now: str) -> None:
    if not _table_exists(connection, "legacy_announcement_baselines_v1"):
        return
    for row in connection.execute("SELECT * FROM legacy_announcement_baselines_v1"):
        identity = row["normalized_path"]
        connection.execute(
            """INSERT INTO shared_announcement_baselines_v2(
               baseline_id,profile_id,inventory_identity,item_type,parent_identity,display_title,year,
               season_number,evidence_json,accepted_at,active,legacy_source
               ) VALUES(?,?,?,?,?,?,?,?,?,?,1,1)""",
            (f"legacy-baseline-{_digest(identity)}","default",identity,row["item_type"],row["parent_normalized_path"],row["title"],row["year"],row["season_number"],json.dumps({"original_path_preserved_in_audit_table": bool(row["original_path"])}),row["captured_at"] or now),
        )


def _copy_legacy_outbox(connection: sqlite3.Connection, now: str) -> None:
    if not _table_exists(connection, "legacy_notification_outbox_v1"):
        return
    for row in connection.execute("SELECT * FROM legacy_notification_outbox_v1"):
        event_id = f"legacy-event-{row['id']}"
        delivered = row["state"] == "DELIVERED"
        connection.execute(
            "INSERT INTO notification_events_v2 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (event_id,row["event_type"],None,"",row["created_at"],"","","",row["payload_json"],"INFO","PRIVATE",f"legacy:{row['event_key']}","",row["created_at"]),
        )
        connection.execute(
            """INSERT INTO notification_outbox(
               outbox_id,event_id,channel_purpose,credential_reference,payload_json,status,attempt_count,
               created_at,updated_at,delivered_at,deduplication_key
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (f"legacy-outbox-{row['id']}",event_id,row["channel_purpose"],"",row["payload_json"],"DELIVERED" if delivered else "FAILED_PERMANENT",row["attempt_count"],row["created_at"],row["delivered_at"] or row["created_at"],row["delivered_at"] if delivered else None,f"{row['channel_purpose']}:legacy:{row['event_key']}"),
        )


def _copy_manual_queue(connection: sqlite3.Connection, now: str) -> None:
    if not _table_exists(connection, "legacy_manual_announcement_queue_v1"):
        return
    for row in connection.execute("SELECT * FROM legacy_manual_announcement_queue_v1"):
        connection.execute(
            "INSERT INTO manual_announcement_drafts VALUES(?,?,?,?,?,?,?,?,?,NULL)",
            (f"legacy-draft-{row['id']}",row["legacy_id"],"default",row["title"],json.dumps({"media_type":row["media_type"],"year":row["year"],"season_number":row["season_number"],"episodes":json.loads(row["episodes_json"] or "[]")}),"DRAFT",f"legacy-manual:{row['legacy_id'] or row['id']}",row["created_at"] or now,row["updated_at"] or now),
        )


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone() is not None


def _digest(value: str) -> str:
    import hashlib
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
