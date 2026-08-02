from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


PRODUCTION_SCHEMA_VERSION = 6
SCHEMA = """
CREATE TABLE IF NOT EXISTS production_migrations (
    migration_id TEXT PRIMARY KEY, source_sha256 TEXT NOT NULL, backup_reference TEXT NOT NULL,
    state TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT, reconciliation_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS inventory_snapshots (
    snapshot_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT NOT NULL,
    status TEXT NOT NULL, roots_json TEXT NOT NULL, statistics_json TEXT NOT NULL,
    diagnostics_json TEXT NOT NULL, inventory_json TEXT NOT NULL, complete INTEGER NOT NULL CHECK(complete IN (0,1))
);
CREATE TABLE IF NOT EXISTS scheduled_run_results (
    run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT NOT NULL, status TEXT NOT NULL,
    refresh_success INTEGER NOT NULL DEFAULT 0, refresh_failed INTEGER NOT NULL DEFAULT 0,
    cache_hits INTEGER NOT NULL DEFAULT 0, inventory_result TEXT NOT NULL DEFAULT 'DISABLED',
    mapping_result TEXT NOT NULL DEFAULT 'DISABLED', events_created INTEGER NOT NULL DEFAULT 0,
    delivered INTEGER NOT NULL DEFAULT 0, retry_count INTEGER NOT NULL DEFAULT 0,
    permanent_failures INTEGER NOT NULL DEFAULT 0, warnings_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS backup_audit (
    backup_id TEXT PRIMARY KEY, reason TEXT NOT NULL, created_at TEXT NOT NULL, path_reference TEXT NOT NULL,
    database_sha256 TEXT NOT NULL, integrity_result TEXT NOT NULL, manifest_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS credential_migration_audit (
    audit_id TEXT PRIMARY KEY, channel_purpose TEXT NOT NULL, credential_reference TEXT NOT NULL,
    provider TEXT NOT NULL, secret_present INTEGER NOT NULL CHECK(secret_present IN (0,1)),
    migrated_at TEXT NOT NULL, legacy_config_retained INTEGER NOT NULL CHECK(legacy_config_retained IN (0,1))
);
CREATE TABLE IF NOT EXISTS cutover_audit (
    cutover_id TEXT PRIMARY KEY, state TEXT NOT NULL, approved_at TEXT, migration_version TEXT NOT NULL,
    backup_reference TEXT NOT NULL, legacy_task_changed INTEGER NOT NULL DEFAULT 0 CHECK(legacy_task_changed IN (0,1)),
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_inventory_complete ON inventory_snapshots(complete,completed_at);
CREATE INDEX IF NOT EXISTS idx_scheduled_runs_time ON scheduled_run_results(started_at);
"""


def migrate_to_production_schema(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON"); versions={int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")}
        if 5 not in versions: raise ValueError("Production schema requires a schema-v5 database.")
        if PRODUCTION_SCHEMA_VERSION in versions: return
        connection.execute("BEGIN IMMEDIATE")
        for statement in SCHEMA.split(";"):
            if statement.strip(): connection.execute(statement)
        connection.execute("INSERT INTO schema_migrations(version,name,applied_at,checksum) VALUES(6,?,?,?)",("production_operations_v6",datetime.now(timezone.utc).isoformat(),"embedded-production-schema-v6"))
        connection.commit()
    except Exception: connection.rollback(); raise
    finally: connection.close()
