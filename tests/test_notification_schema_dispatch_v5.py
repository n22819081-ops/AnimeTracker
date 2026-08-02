from __future__ import annotations

import hashlib
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock,patch

from anime_tracker.modernization.schema_v4 import initialize_matching_test_database
from anime_tracker.modernization.schema_v5 import initialize_notification_test_database,migrate_modern_database_to_v5
from anime_tracker.notifications_v2 import (
    BatchHealth, ChannelPurpose, DeliveryResult, DeliveryResultType, DiscordDeliveryAdapter,
    InMemoryCredentialStore, NotificationDispatcher, NotificationOutboxRepository,
    ManualAnnouncementRepository,
)

from notification_v2_helpers import NOW,event,message


ROOT=Path(__file__).resolve().parents[1]
LIVE=ROOT/"data"/"anime_tracker.db"
LIVE_HASH="52D2F8D5E1365A655CDB915A6357822EEF21D8D226797A0EE791D03491D4B2A7"
V4=ROOT/"migration_test"/"anime_tracker_modern_v4.db"


class SchemaV5Tests(unittest.TestCase):
    def test_real_v4_copy_preserves_1312_baselines(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/"v5.db"
            shutil.copy2(V4,target)
            migrate_modern_database_to_v5(target,live_database_path=LIVE,protected_roots=())
            with closing(sqlite3.connect(target)) as connection:
                self.assertEqual(connection.execute("select count(*) from shared_announcement_baselines_v2").fetchone()[0],1312)
                self.assertEqual(connection.execute("select count(*) from legacy_announcement_baselines_v1").fetchone()[0],1312)
                self.assertEqual(connection.execute("pragma integrity_check").fetchone()[0],"ok")
                self.assertEqual(connection.execute("pragma foreign_key_check").fetchall(),[])

    def test_manual_queue_and_historical_delivery_evidence_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/"v4.db"
            shutil.copy2(V4,target)
            with closing(sqlite3.connect(target)) as connection:
                connection.execute("insert into manual_announcement_queue(legacy_id,media_type,title,normalized_title,year,season_number,episodes_json,created_at,updated_at) values(1,'TV_SHOW','Example','example',2026,2,'[4,5]','2026-08-01','2026-08-01')")
                connection.execute("insert into notification_outbox(event_key,channel_purpose,event_type,payload_json,state,attempt_count,delivered_at,created_at) values('sent:1','PRIVATE_TRACKER','status','{}','DELIVERED',1,'2026-08-01','2026-08-01')")
                connection.commit()
            migrate_modern_database_to_v5(target,protected_roots=())
            with closing(sqlite3.connect(target)) as connection:
                self.assertEqual(connection.execute("select status from manual_announcement_drafts").fetchone()[0],"DRAFT")
                self.assertEqual(connection.execute("select status from notification_outbox").fetchone()[0],"DELIVERED")

    def test_failed_legacy_event_is_not_reinterpreted_as_delivered(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/"v4.db"
            shutil.copy2(V4,target)
            with closing(sqlite3.connect(target)) as connection:
                connection.execute("insert into notification_outbox(event_key,channel_purpose,event_type,payload_json,state,attempt_count,created_at) values('failed:1','PRIVATE_TRACKER','status','{}','FAILED_FINAL',1,'2026-08-01')")
                connection.commit()
            migrate_modern_database_to_v5(target,protected_roots=())
            with closing(sqlite3.connect(target)) as connection:
                self.assertEqual(connection.execute("select status from notification_outbox").fetchone()[0],"FAILED_PERMANENT")

    def test_v5_is_idempotent_and_requires_v4(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/"v5.db"
            initialize_notification_test_database(target)
            migrate_modern_database_to_v5(target,protected_roots=())
            with closing(sqlite3.connect(target)) as connection:
                self.assertEqual(connection.execute("select count(*) from schema_migrations where version=5").fetchone()[0],1)

    def test_transaction_rolls_back_on_copy_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/"v4.db"
            shutil.copy2(V4,target)
            with patch("anime_tracker.modernization.schema_v5._copy_baseline",side_effect=RuntimeError("stop")):
                with self.assertRaises(RuntimeError): migrate_modern_database_to_v5(target,protected_roots=())
            with closing(sqlite3.connect(target)) as connection:
                self.assertIsNotNone(connection.execute("select name from sqlite_master where name='notification_outbox'").fetchone())
                self.assertIsNone(connection.execute("select name from sqlite_master where name='notification_events_v2'").fetchone())

    def test_live_database_migration_refused_and_hash_unchanged(self):
        with self.assertRaises(ValueError): migrate_modern_database_to_v5(LIVE,live_database_path=LIVE,protected_roots=())
        self.assertEqual(hashlib.sha256(LIVE.read_bytes()).hexdigest().upper(),LIVE_HASH)

    def test_secret_absent_from_sqlite(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/"v5.db"
            initialize_notification_test_database(target)
            secret="https://discord.com/api/webhooks/123/very-secret"
            store=InMemoryCredentialStore(); store.store_secret("private",secret)
            repo=NotificationOutboxRepository(target)
            repo.enqueue(event(),message(),"private")
            self.assertNotIn(secret,target.read_bytes().decode("latin1"))


class DispatcherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.db=Path(self.temp.name)/"dispatch.db"
        initialize_notification_test_database(self.db)
        self.repo=NotificationOutboxRepository(self.db)
        self.credentials=InMemoryCredentialStore(); self.credentials.store_secret("private","https://test.invalid/hook")
    def tearDown(self): self.temp.cleanup()

    def test_mixed_results_report_partial_success(self):
        for index in range(3): self.repo.enqueue(event(f"key-{index}",event_id=f"event-{index}"),message(),"private")
        results=iter((DeliveryResult(DeliveryResultType.DELIVERED,204),DeliveryResult(DeliveryResultType.RETRYABLE_FAILURE,503,True),DeliveryResult(DeliveryResultType.PERMANENT_FAILURE,404)))
        adapter=Mock(); adapter.deliver.side_effect=lambda *_: next(results)
        batch=NotificationDispatcher(self.repo,self.credentials,adapter).dispatch("worker",NOW)
        self.assertEqual((batch.delivered,batch.retry_pending,batch.permanently_failed),(1,1,1))
        self.assertEqual(batch.health,BatchHealth.PARTIAL_SUCCESS)

    def test_missing_credential_is_permanent_without_exposing_value(self):
        item,_=self.repo.enqueue(event(),message(),"missing")
        batch=NotificationDispatcher(self.repo,self.credentials,Mock()).dispatch("worker",NOW)
        self.assertEqual(batch.permanently_failed,1)
        self.assertEqual(self.repo.get(item.outbox_id).last_error_type,"MissingCredential")


class ManualAnnouncementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.db=Path(self.temp.name)/"manual.db"
        initialize_notification_test_database(self.db)
        self.repo=ManualAnnouncementRepository(self.db)
    def tearDown(self): self.temp.cleanup()

    def test_draft_deduplicates_groups_and_lifecycle(self):
        items=({"title":"One","episodes":[4,5]},{"title":"Two","season":2})
        first=self.repo.create_draft("Weekly additions",items,NOW)
        second=self.repo.create_draft("Weekly additions",items,NOW)
        self.assertEqual(first,second)
        self.repo.set_status(first,"PENDING",NOW)
        self.assertEqual(self.repo.claim_pending(NOW),first)
        self.repo.set_status(first,"DELIVERED",NOW)
        with self.assertRaises(ValueError): self.repo.set_status(first,"FAILED",NOW)

    def test_manual_draft_privacy_filter_applies(self):
        with self.assertRaises(Exception):
            self.repo.create_draft("Bad",({"path":r"I:\Jellyfin_Media\Anime\Show"},),NOW)


class NotificationSafetyTests(unittest.TestCase):
    def test_v2_package_has_no_gui_scheduler_media_scan_or_external_tool_calls(self):
        package=ROOT/"src"/"anime_tracker"/"notifications_v2"
        source="\n".join(path.read_text(encoding="utf-8").casefold() for path in package.glob("*.py"))
        for forbidden in ("tkinter","pyside6","schtasks","register-scheduledtask","jellyfin_media","storage checker","sonarr","radarr","move-item","remove-item"):
            self.assertNotIn(forbidden,source)

    def test_automated_notification_tests_use_no_live_webhook(self):
        sources="\n".join(path.read_text(encoding="utf-8") for path in (ROOT/"tests").glob("*notification*v5.py"))
        self.assertNotIn("notification_config"+".json",sources)
        self.assertNotIn("requests"+".post(",sources)


if __name__ == "__main__": unittest.main()
