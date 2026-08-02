from __future__ import annotations

import json
import shutil
import sqlite3

import pytest

from anime_tracker.modernization.backup import sha256_file
from anime_tracker.production.backup_restore import ModernBackupManager,ModernRestoreManager,RestoreError
from anime_tracker.production.credentials import DpapiCredentialStore,PRIVATE_REFERENCE,SHARED_REFERENCE,migrate_legacy_credentials
from anime_tracker.production.diagnostics import DiagnosticsReporter
from anime_tracker.production.notifications import ProductionNotificationActivation
from anime_tracker.notifications_v2.enums import ChannelPurpose,DeliveryResultType
from anime_tracker.notifications_v2.models import DeliveryResult
from production_helpers import LEGACY,production_profile


class FakeProtector:
    def protect(self,value):return b"protected:"+value[::-1]
    def unprotect(self,value):return value.removeprefix(b"protected:")[::-1]


def test_private_and_shared_credentials_migrate_separately_without_sqlite_secret(tmp_path):
    profile=production_profile(tmp_path);config=tmp_path/"notification_config.json";private="https://discord.com/api/webhooks/1/private";shared="https://discord.com/api/webhooks/2/shared";config.write_text(json.dumps({"discord_webhook_url":private,"shared_discord_webhook_url":shared}))
    store=DpapiCredentialStore(profile.credentials_dir,FakeProtector())
    with pytest.raises(PermissionError):migrate_legacy_credentials(profile,config,approved=False,store=store)
    result=migrate_legacy_credentials(profile,config,approved=True,store=store)
    assert result["legacy_config_retained"] and not result["delivery_enabled"]
    assert store.retrieve_secret(PRIVATE_REFERENCE).reveal()==private and store.retrieve_secret(SHARED_REFERENCE).reveal()==shared
    data=profile.database_path.read_bytes().decode("utf-8",errors="ignore");assert private not in data and shared not in data


def test_backup_has_manifest_hash_integrity_and_no_raw_credential(tmp_path):
    profile=production_profile(tmp_path);manager=ModernBackupManager(profile);backup=manager.create("MANUAL")
    metadata=json.loads((backup/"backup_metadata.json").read_text());assert metadata["integrity_result"]=="ok" and metadata["schema_version"]==6
    assert not metadata["raw_credentials_included"] and (backup/"manifest.json").is_file()


def test_restore_rejects_corruption_and_preserves_legacy(tmp_path):
    profile=production_profile(tmp_path);legacy_before=sha256_file(LEGACY);manager=ModernBackupManager(profile);backup=manager.create("MANUAL");restore=ModernRestoreManager(profile,manager)
    valid=restore.validate(backup);assert valid["integrity_result"]=="ok"
    bad=tmp_path/"bad";shutil.copytree(backup,bad);(bad/"anime_tracker_modern.db").write_bytes(b"corrupt")
    with pytest.raises(RestoreError):restore.validate(bad)
    with pytest.raises(PermissionError):restore.restore(backup,approved=False)
    result=restore.restore(backup,approved=True);assert result["restored"] and result["integrity"]=="ok" and sha256_file(LEGACY)==legacy_before


def test_retention_is_dry_run_and_protected_backups_are_not_eligible(tmp_path):
    profile=production_profile(tmp_path);manager=ModernBackupManager(profile);manager.create("PRE_MIGRATION");plan=manager.retention_preview()
    assert plan["keep"] and all(path.exists() for path in plan["keep"]);assert all("pre-migration" not in path.name for path in plan["eligible_for_review"])


def test_support_report_redacts_paths_credentials_and_machine_identity(tmp_path):
    profile=production_profile(tmp_path);report_path=tmp_path/"support.json";DiagnosticsReporter(profile).write_support_report(report_path);text=report_path.read_text(encoding="utf-8").casefold()
    assert "production profile" in text and "credential" in text
    assert str(profile.root).casefold() not in text and "discord.com/api/webhooks" not in text
    assert "computer_name" in text and '"computer_name": false' in text


def test_notification_baseline_preview_and_acceptance_create_no_flood(tmp_path):
    profile=production_profile(tmp_path);activation=ProductionNotificationActivation(profile,store=object(),adapter=object());preview=activation.baseline_preview()
    assert preview["baseline_rows"]==1312 and preview["existing_content_events"]==0 and preview["existing_episode_events"]==0
    with pytest.raises(PermissionError):activation.accept_baseline(approved=False)
    accepted=activation.accept_baseline(approved=True);assert accepted["accepted"] and profile.load_bootstrap()["initial_events_created"]==0


def test_notification_stages_require_sequential_explicit_approval(tmp_path):
    profile=production_profile(tmp_path);activation=ProductionNotificationActivation(profile,store=object(),adapter=object())
    with pytest.raises(PermissionError):activation.activate_stage(2,approved=False)
    with pytest.raises(ValueError):activation.activate_stage(4,approved=True)
    assert activation.activate_stage(2,approved=True)["name"]=="CHANNEL_TESTS"
    assert activation.activate_stage(3,approved=True)["private_enabled"]
    assert not profile.load_bootstrap()["shared_notifications_enabled"]


def test_channel_test_does_not_advance_baseline_and_keeps_channels_separate(tmp_path):
    profile=production_profile(tmp_path)
    class Store:
        def retrieve_secret(self,reference):
            from anime_tracker.notifications_v2.credentials import SecretValue
            return SecretValue("private" if "private" in reference else "shared")
    calls=[]
    class Adapter:
        def deliver(self,secret,message):calls.append((secret,message.channel_purpose));return DeliveryResult(DeliveryResultType.DELIVERED)
    activation=ProductionNotificationActivation(profile,Store(),Adapter());before=profile.load_bootstrap()["initial_baseline_accepted"]
    activation.test_channel(ChannelPurpose.PRIVATE_TRACKER,approved=True);activation.test_channel(ChannelPurpose.SHARED_ANNOUNCEMENT,approved=True)
    assert calls==[("private",ChannelPurpose.PRIVATE_TRACKER),("shared",ChannelPurpose.SHARED_ANNOUNCEMENT)]
    assert profile.load_bootstrap()["initial_baseline_accepted"]==before
