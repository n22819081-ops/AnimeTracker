from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .safety import assert_safe_output_path

MODERN_SCHEMA_VERSION = 1

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    checksum TEXT NOT NULL DEFAULT ''
);

CREATE TABLE anilist_media (
    anilist_id INTEGER PRIMARY KEY CHECK(anilist_id > 0),
    media_format TEXT NOT NULL DEFAULT '',
    season_name TEXT NOT NULL DEFAULT '',
    season_year INTEGER,
    episode_count INTEGER,
    anilist_status TEXT NOT NULL DEFAULT '',
    start_date TEXT NOT NULL DEFAULT '',
    end_date TEXT NOT NULL DEFAULT '',
    cover_image_url TEXT NOT NULL DEFAULT '',
    page_url TEXT NOT NULL DEFAULT '',
    relation_label_legacy TEXT NOT NULL DEFAULT '',
    source_updated_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE media_titles (
    id INTEGER PRIMARY KEY,
    anilist_id INTEGER NOT NULL REFERENCES anilist_media(anilist_id) ON DELETE RESTRICT,
    title_type TEXT NOT NULL CHECK(title_type IN ('english', 'romaji', 'native', 'synonym')),
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL DEFAULT '',
    UNIQUE(anilist_id, title_type, title)
);

CREATE TABLE media_relations (
    source_anilist_id INTEGER NOT NULL REFERENCES anilist_media(anilist_id) ON DELETE RESTRICT,
    target_anilist_id INTEGER NOT NULL,
    relation_type TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'AniList',
    confirmed INTEGER NOT NULL DEFAULT 0 CHECK(confirmed IN (0, 1)),
    PRIMARY KEY(source_anilist_id, target_anilist_id, relation_type)
);

CREATE TABLE franchise_groups (
    id INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL,
    confirmation_state TEXT NOT NULL DEFAULT 'unconfirmed'
);

CREATE TABLE franchise_members (
    franchise_group_id INTEGER NOT NULL REFERENCES franchise_groups(id) ON DELETE CASCADE,
    anilist_id INTEGER NOT NULL REFERENCES anilist_media(anilist_id) ON DELETE RESTRICT,
    role TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(franchise_group_id, anilist_id)
);

CREATE TABLE tracked_media (
    id INTEGER PRIMARY KEY,
    anilist_id INTEGER NOT NULL REFERENCES anilist_media(anilist_id) ON DELETE RESTRICT,
    legacy_anime_id INTEGER,
    added_at TEXT NOT NULL,
    archived_at TEXT,
    archive_reason TEXT NOT NULL DEFAULT '',
    manual_notes TEXT NOT NULL DEFAULT '',
    legacy_payload_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(anilist_id),
    UNIQUE(legacy_anime_id)
);

CREATE TABLE tracking_state (
    tracked_media_id INTEGER PRIMARY KEY REFERENCES tracked_media(id) ON DELETE CASCADE,
    tracker_status TEXT NOT NULL,
    server_presence TEXT NOT NULL CHECK(server_presence IN ('NOT_ON_SERVER', 'PARTIAL', 'ON_SERVER', 'UNKNOWN_COVERAGE', 'NEEDS_REVIEW')),
    episode_coverage TEXT NOT NULL CHECK(episode_coverage IN ('NONE', 'PARTIAL', 'CURRENT_COMPLETE', 'COMPLETE', 'UNKNOWN')),
    review_status TEXT NOT NULL CHECK(review_status IN ('NONE', 'OPEN', 'RESOLVED')),
    review_reason TEXT NOT NULL DEFAULT '',
    movie_availability TEXT NOT NULL DEFAULT 'unknown',
    legacy_server_status TEXT NOT NULL DEFAULT '',
    last_checked TEXT NOT NULL DEFAULT ''
);

CREATE TABLE server_library_items (
    id INTEGER PRIMARY KEY,
    library_kind TEXT NOT NULL CHECK(library_kind IN ('TV', 'MOVIE', 'UNKNOWN')),
    normalized_path TEXT NOT NULL UNIQUE,
    original_path TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    year INTEGER,
    jellyfin_item_id TEXT,
    last_seen_at TEXT NOT NULL DEFAULT '',
    missing_since TEXT
);

CREATE TABLE server_seasons (
    id INTEGER PRIMARY KEY,
    library_item_id INTEGER NOT NULL REFERENCES server_library_items(id) ON DELETE CASCADE,
    season_number INTEGER NOT NULL CHECK(season_number >= 0),
    expected_episode_count INTEGER,
    present_episode_count INTEGER,
    coverage_state TEXT NOT NULL DEFAULT 'UNKNOWN',
    UNIQUE(library_item_id, season_number)
);

CREATE TABLE server_episodes (
    id INTEGER PRIMARY KEY,
    server_season_id INTEGER NOT NULL REFERENCES server_seasons(id) ON DELETE CASCADE,
    episode_number INTEGER NOT NULL CHECK(episode_number > 0),
    absolute_episode_number INTEGER,
    normalized_path TEXT NOT NULL DEFAULT '',
    original_path TEXT NOT NULL DEFAULT '',
    present INTEGER NOT NULL DEFAULT 1 CHECK(present IN (0, 1)),
    UNIQUE(server_season_id, episode_number)
);

CREATE TABLE server_movies (
    library_item_id INTEGER PRIMARY KEY REFERENCES server_library_items(id) ON DELETE CASCADE,
    present INTEGER NOT NULL DEFAULT 1 CHECK(present IN (0, 1)),
    digital_availability TEXT NOT NULL DEFAULT 'unknown'
);

CREATE TABLE server_specials (
    id INTEGER PRIMARY KEY,
    library_item_id INTEGER NOT NULL REFERENCES server_library_items(id) ON DELETE CASCADE,
    season_number INTEGER NOT NULL DEFAULT 0,
    mapping_kind TEXT NOT NULL CHECK(mapping_kind IN ('SEASON_00', 'MOVIE', 'SEPARATE_SERIES', 'UNKNOWN')),
    confirmed INTEGER NOT NULL DEFAULT 0 CHECK(confirmed IN (0, 1))
);

CREATE TABLE media_server_mappings (
    id INTEGER PRIMARY KEY,
    tracked_media_id INTEGER NOT NULL REFERENCES tracked_media(id) ON DELETE CASCADE,
    library_item_id INTEGER NOT NULL REFERENCES server_library_items(id) ON DELETE RESTRICT,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('SERIES', 'SEASON', 'MOVIE', 'SPECIAL', 'UNSPECIFIED')),
    season_number INTEGER,
    confirmation_type TEXT NOT NULL,
    confidence INTEGER,
    confirmed_at TEXT NOT NULL,
    legacy_anilist_id INTEGER,
    UNIQUE(tracked_media_id, library_item_id, target_kind, season_number)
);

CREATE TABLE jellyfin_folder_mappings (
    id INTEGER PRIMARY KEY,
    library_item_id INTEGER NOT NULL REFERENCES server_library_items(id) ON DELETE CASCADE,
    normalized_folder_path TEXT NOT NULL,
    original_folder_path TEXT NOT NULL,
    mapping_scope TEXT NOT NULL CHECK(mapping_scope IN ('SHOW', 'SEASON', 'MOVIE', 'SPECIAL')),
    season_number INTEGER,
    UNIQUE(library_item_id, normalized_folder_path, mapping_scope, season_number)
);

CREATE TABLE episode_mappings (
    id INTEGER PRIMARY KEY,
    tracked_media_id INTEGER NOT NULL REFERENCES tracked_media(id) ON DELETE CASCADE,
    server_episode_id INTEGER NOT NULL REFERENCES server_episodes(id) ON DELETE CASCADE,
    provider_episode_number INTEGER,
    confirmed INTEGER NOT NULL DEFAULT 0 CHECK(confirmed IN (0, 1)),
    UNIQUE(tracked_media_id, server_episode_id)
);

CREATE TABLE rejected_match_decisions (
    id INTEGER PRIMARY KEY,
    tracked_media_id INTEGER NOT NULL REFERENCES tracked_media(id) ON DELETE CASCADE,
    normalized_path TEXT NOT NULL DEFAULT '',
    original_path TEXT NOT NULL DEFAULT '',
    block_auto_match INTEGER NOT NULL DEFAULT 0 CHECK(block_auto_match IN (0, 1)),
    reason TEXT NOT NULL DEFAULT '',
    decided_at TEXT NOT NULL,
    legacy_anilist_id INTEGER,
    UNIQUE(tracked_media_id, normalized_path, block_auto_match)
);

CREATE TABLE match_candidates (
    id INTEGER PRIMARY KEY,
    tracked_media_id INTEGER NOT NULL REFERENCES tracked_media(id) ON DELETE CASCADE,
    normalized_path TEXT NOT NULL,
    original_path TEXT NOT NULL,
    confidence_label TEXT NOT NULL,
    score INTEGER NOT NULL,
    reasons_json TEXT NOT NULL,
    folder_year INTEGER,
    media_kind TEXT NOT NULL,
    scanned_at TEXT NOT NULL,
    UNIQUE(tracked_media_id, normalized_path)
);

CREATE TABLE manual_overrides (
    id INTEGER PRIMARY KEY,
    tracked_media_id INTEGER NOT NULL REFERENCES tracked_media(id) ON DELETE CASCADE,
    override_type TEXT NOT NULL,
    value_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE review_cases (
    id INTEGER PRIMARY KEY,
    tracked_media_id INTEGER REFERENCES tracked_media(id) ON DELETE CASCADE,
    review_type TEXT NOT NULL,
    reason TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('OPEN', 'RESOLVED', 'DISMISSED')),
    opened_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE status_history (
    id INTEGER PRIMARY KEY,
    tracked_media_id INTEGER REFERENCES tracked_media(id) ON DELETE SET NULL,
    legacy_history_id INTEGER UNIQUE,
    event_type TEXT NOT NULL,
    previous_tracker_status TEXT NOT NULL DEFAULT '',
    new_tracker_status TEXT NOT NULL DEFAULT '',
    server_path_snapshot TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE scan_sessions (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    result TEXT NOT NULL DEFAULT 'RUNNING',
    read_only INTEGER NOT NULL DEFAULT 1 CHECK(read_only = 1),
    warning_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE anilist_refresh_batches (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    requested_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    result TEXT NOT NULL DEFAULT 'RUNNING'
);

CREATE TABLE anilist_cache (
    anilist_id INTEGER PRIMARY KEY,
    payload_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY(anilist_id) REFERENCES anilist_media(anilist_id) ON DELETE CASCADE
);

CREATE TABLE notification_outbox (
    id INTEGER PRIMARY KEY,
    event_key TEXT NOT NULL UNIQUE,
    channel_purpose TEXT NOT NULL CHECK(channel_purpose IN ('PRIVATE_TRACKER', 'SHARED_ANNOUNCEMENT')),
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('PENDING', 'CLAIMED', 'DELIVERED', 'FAILED_RETRYABLE', 'FAILED_FINAL')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    claimed_at TEXT,
    delivered_at TEXT,
    last_error_type TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE notification_deliveries (
    id INTEGER PRIMARY KEY,
    outbox_id INTEGER NOT NULL REFERENCES notification_outbox(id) ON DELETE CASCADE,
    attempted_at TEXT NOT NULL,
    delivered INTEGER NOT NULL CHECK(delivered IN (0, 1)),
    http_status INTEGER,
    error_type TEXT NOT NULL DEFAULT ''
);

CREATE TABLE announcement_baselines (
    id INTEGER PRIMARY KEY,
    channel_purpose TEXT NOT NULL DEFAULT 'SHARED_ANNOUNCEMENT',
    item_type TEXT NOT NULL,
    normalized_path TEXT NOT NULL,
    parent_normalized_path TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    year INTEGER,
    season_number INTEGER,
    original_path TEXT NOT NULL DEFAULT '',
    captured_at TEXT NOT NULL,
    UNIQUE(channel_purpose, normalized_path)
);

CREATE TABLE manual_announcement_queue (
    id INTEGER PRIMARY KEY,
    legacy_id INTEGER UNIQUE,
    media_type TEXT NOT NULL,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    year INTEGER,
    season_number INTEGER,
    episodes_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE manual_announcement_titles (
    id INTEGER PRIMARY KEY,
    media_type TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    title TEXT NOT NULL,
    year INTEGER,
    last_used_at TEXT NOT NULL,
    UNIQUE(media_type, normalized_title)
);

CREATE TABLE application_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    contains_secret INTEGER NOT NULL DEFAULT 0 CHECK(contains_secret = 0)
);

CREATE TABLE credential_references (
    id INTEGER PRIMARY KEY,
    channel_purpose TEXT NOT NULL UNIQUE CHECK(channel_purpose IN ('PRIVATE_TRACKER', 'SHARED_ANNOUNCEMENT', 'JELLYFIN_READ_ONLY')),
    credential_provider TEXT NOT NULL CHECK(credential_provider IN ('WINDOWS_CREDENTIAL_MANAGER', 'WINDOWS_DPAPI')),
    credential_identifier TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE archived_legacy_records (
    id INTEGER PRIMARY KEY,
    source_table TEXT NOT NULL,
    source_key TEXT NOT NULL,
    legacy_anilist_id INTEGER,
    reason TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    requires_manual_review INTEGER NOT NULL DEFAULT 1 CHECK(requires_manual_review IN (0, 1)),
    archived_at TEXT NOT NULL,
    UNIQUE(source_table, source_key)
);

CREATE TABLE migration_audit (
    id INTEGER PRIMARY KEY,
    migration_version INTEGER NOT NULL,
    source_table TEXT NOT NULL,
    source_count INTEGER NOT NULL,
    migrated_active_count INTEGER NOT NULL,
    archived_count INTEGER NOT NULL,
    excluded_technical_count INTEGER NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    completed_at TEXT NOT NULL,
    CHECK(source_count = migrated_active_count + archived_count + excluded_technical_count)
);

CREATE INDEX idx_media_titles_normalized ON media_titles(normalized_title);
CREATE INDEX idx_mappings_library_item ON media_server_mappings(library_item_id);
CREATE INDEX idx_rejections_tracked_media ON rejected_match_decisions(tracked_media_id);
CREATE INDEX idx_review_cases_state ON review_cases(state);
CREATE INDEX idx_outbox_state_attempt ON notification_outbox(state, next_attempt_at);
CREATE INDEX idx_archive_source ON archived_legacy_records(source_table, legacy_anilist_id);
"""


def create_modern_database(
    path: Path,
    *,
    protected_roots: tuple[Path, ...] | None = None,
    storage_checker_path: Path | None = None,
) -> None:
    kwargs = {"storage_checker_path": storage_checker_path}
    if protected_roots is not None:
        kwargs["protected_roots"] = protected_roots
    assert_safe_output_path(path, **kwargs)
    if path.exists():
        raise FileExistsError(f"Modern database destination already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA_SQL)
        connection.execute(
            "INSERT INTO schema_migrations(version, name, applied_at, checksum) VALUES(?, ?, ?, ?)",
            (MODERN_SCHEMA_VERSION, "modern_schema_v1", datetime.now(timezone.utc).isoformat(), "embedded-schema-v1"),
        )
        connection.commit()
    except Exception:
        connection.close()
        path.unlink(missing_ok=True)
        raise
    finally:
        if path.exists():
            connection.close()
