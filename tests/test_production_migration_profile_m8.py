from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from anime_tracker.modernization.backup import sha256_file
from anime_tracker.production.comparison import build_legacy_modern_comparison
from anime_tracker.production.cutover import CUTOVER_PHRASE,approve_cutover,rollback_to_legacy
from anime_tracker.production.locks import FileOperationLock,OperationAlreadyRunning
from anime_tracker.production.migration import ProductionMigrator
from anime_tracker.production.profile import LIVE_LEGACY_DATABASE,ProductionProfile,default_bootstrap
from production_helpers import LEGACY,production_profile,verified_legacy_backup


def test_production_profile_is_separate_and_defaults_are_disabled(tmp_path):
    profile=ProductionProfile(tmp_path/"profile");profile.initialize_directories();settings=profile.load_bootstrap()
    assert profile.database_path!=LIVE_LEGACY_DATABASE
    assert settings["cutover_state"]=="PENDING_APPROVAL"
    assert settings["notifications_stage"]==1
    assert not settings["anilist_refresh_enabled"] and not settings["jellyfin_scan_enabled"]


def test_profile_settings_strip_secret_like_values(tmp_path):
    profile=ProductionProfile(tmp_path/"profile");profile.initialize_directories();profile.save_settings({"theme":"Dark","webhook_url":"secret","api_token":"secret"})
    text=profile.settings_path.read_text(encoding="utf-8");assert "secret" not in text and "webhook" not in text and "token" not in text


def test_production_reset_requires_exact_phrase_and_verified_backup(tmp_path):
    profile=ProductionProfile(tmp_path/"profile");profile.initialize_directories()
    with pytest.raises(PermissionError):profile.assert_reset_allowed(confirmation="yes",verified_backup=None)
    backup=tmp_path/"backup";backup.mkdir();(backup/"manifest.json").write_text("{}")
    profile.assert_reset_allowed(confirmation="RESET MODERN PRODUCTION PROFILE",verified_backup=backup)


def test_migration_preserves_exact_counts_no_loss_no_webhook_and_legacy_unchanged(tmp_path):
    backup=verified_legacy_backup(tmp_path);profile=ProductionProfile(tmp_path/"profile");before=sha256_file(LEGACY)
    result=ProductionMigrator(profile,live_database=LEGACY).migrate_from_verified_backup(backup)
    assert result["valid"] and not result["errors"]
    assert result["counts"]["active_titles"]==69
    assert result["counts"]["archived_orphans"]==421
    assert result["counts"]["shared_baselines"]==1312
    assert result["counts"]["foreign_key_violations"]==0
    assert result["reconciliation"]["unexplained_loss_tables"]==[]
    assert sha256_file(LEGACY)==before
    assert "discord.com/api/webhooks" not in profile.database_path.read_bytes().decode("utf-8",errors="ignore").casefold()


def test_migration_restart_returns_valid_existing_database(tmp_path):
    backup=verified_legacy_backup(tmp_path);profile=ProductionProfile(tmp_path/"profile");migrator=ProductionMigrator(profile,live_database=LEGACY)
    first=migrator.migrate_from_verified_backup(backup);second=migrator.migrate_from_verified_backup(backup)
    assert first["valid"] and second["valid"] and second["counts"]["active_titles"]==69


def test_migration_does_not_invent_season_scope(tmp_path):
    backup=verified_legacy_backup(tmp_path);profile=ProductionProfile(tmp_path/"profile");ProductionMigrator(profile,live_database=LEGACY).migrate_from_verified_backup(backup)
    with sqlite3.connect(profile.database_path) as connection:
        rows=connection.execute("SELECT target_type,season_number FROM media_server_mappings WHERE active=1").fetchall()
    assert rows==[("UNKNOWN_TARGET",None)]


def test_file_lock_prevents_parallel_migration_or_scheduled_work(tmp_path):
    path=tmp_path/"operation.lock"
    with FileOperationLock(path):
        with pytest.raises(OperationAlreadyRunning):FileOperationLock(path).acquire()
    assert not path.exists()


def test_comparison_covers_all_69_records_without_overwriting(tmp_path):
    profile=production_profile(tmp_path);before=sha256_file(profile.database_path);report=build_legacy_modern_comparison(LEGACY,profile.database_path)
    assert report["active_records_compared"]==69 and len(report["records"])==69
    assert report["possible_migration_errors"]==0 and sha256_file(profile.database_path)==before


def test_cutover_requires_phrase_and_rollback_preserves_modern_database(tmp_path):
    backup=verified_legacy_backup(tmp_path);profile=ProductionProfile(tmp_path/"profile");ProductionMigrator(profile,live_database=LEGACY).migrate_from_verified_backup(backup)
    with pytest.raises(PermissionError):approve_cutover(profile,confirmation="approve")
    result=approve_cutover(profile,confirmation=CUTOVER_PHRASE);assert result["legacy_preserved"] and not result["legacy_task_changed"]
    rolled=rollback_to_legacy(profile,approved=True);assert rolled["modern_database_preserved"] and not rolled["media_restore_required"]
