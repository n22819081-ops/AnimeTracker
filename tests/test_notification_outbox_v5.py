from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path

from anime_tracker.modernization.schema_v5 import initialize_notification_test_database
from anime_tracker.notifications_v2 import (
    ChannelPurpose, DeliveryResult, DeliveryResultType, NotificationOutboxRepository, OutboxStatus,
)

from notification_v2_helpers import NOW, event, message


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "notifications.db"
        initialize_notification_test_database(self.db)
        self.repo = NotificationOutboxRepository(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def enqueue(self, key="event-key", channel=ChannelPurpose.PRIVATE_TRACKER, **kwargs):
        return self.repo.enqueue(event(key, event_id=f"event-{key}"), message(channel), "credential/private", **kwargs)

    def test_enqueue_and_repeated_processing_deduplicates(self):
        first, created = self.enqueue()
        second, duplicate = self.enqueue()
        self.assertTrue(created)
        self.assertFalse(duplicate)
        self.assertEqual(first.outbox_id, second.outbox_id)

    def test_private_and_shared_channels_are_separate(self):
        private, _ = self.enqueue()
        shared, created = self.enqueue(channel=ChannelPurpose.SHARED_ANNOUNCEMENT)
        self.assertTrue(created)
        self.assertNotEqual(private.outbox_id, shared.outbox_id)

    def test_suppressed_event_is_recorded(self):
        item, _ = self.enqueue(suppressed_reason="title snoozed")
        self.assertEqual(item.status, OutboxStatus.SUPPRESSED)
        self.assertEqual(self.repo.claim_batch("worker", NOW), ())

    def test_title_event_channel_and_date_suppression(self):
        self.repo.save_suppression(
            "snooze",ChannelPurpose.PRIVATE_TRACKER,NOW-timedelta(minutes=1),
            anilist_id=100,event_type="NEW_EPISODE_AIRED",ends_at=NOW+timedelta(days=1),reason="vacation",
        )
        item,_=self.enqueue()
        self.assertEqual(item.status,OutboxStatus.SUPPRESSED)
        self.repo.clear_suppression("snooze",NOW)
        later,_=self.enqueue("later")
        self.assertEqual(later.status,OutboxStatus.PENDING)

    def test_channel_event_filter_is_independent(self):
        self.repo.set_event_filter(ChannelPurpose.SHARED_ANNOUNCEMENT,"NEW_EPISODE_AIRED",False)
        shared,_=self.enqueue("shared-filter",ChannelPurpose.SHARED_ANNOUNCEMENT)
        private,_=self.enqueue("private-filter",ChannelPurpose.PRIVATE_TRACKER)
        self.assertEqual(shared.status,OutboxStatus.SUPPRESSED)
        self.assertEqual(private.status,OutboxStatus.PENDING)

    def test_atomic_claim_and_ownership(self):
        item, _ = self.enqueue()
        claimed = self.repo.claim_batch("one", NOW)
        self.assertEqual(claimed[0].outbox_id, item.outbox_id)
        self.assertEqual(self.repo.claim_batch("two", NOW), ())
        with self.assertRaises(PermissionError):
            self.repo.complete(item.outbox_id, "two", DeliveryResult(DeliveryResultType.DELIVERED), NOW)

    def test_two_worker_race_claims_once(self):
        self.enqueue()
        barrier = threading.Barrier(2)
        results = []
        errors = []

        def claim(worker):
            try:
                barrier.wait()
                results.extend(self.repo.claim_batch(worker, NOW))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=claim,args=(name,)) for name in ("one","two")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 1)

    def test_claim_expiration_and_recovery(self):
        self.enqueue()
        self.repo.claim_batch("crashed", NOW, lease=timedelta(seconds=30))
        recovered = self.repo.claim_batch("recovery", NOW + timedelta(seconds=31))
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].claimed_by, "recovery")

    def test_success_is_delivered_and_immutable_to_claiming(self):
        item, _ = self.enqueue()
        self.repo.claim_batch("worker", NOW)
        updated = self.repo.complete(item.outbox_id,"worker",DeliveryResult(DeliveryResultType.DELIVERED,204),NOW)
        self.assertEqual(updated.status, OutboxStatus.DELIVERED)
        self.assertIsNotNone(updated.delivered_at)
        self.assertEqual(self.repo.claim_batch("other", NOW + timedelta(days=1)), ())

    def test_retryable_failure_remains_retryable_and_not_delivered(self):
        item, _ = self.enqueue()
        self.repo.claim_batch("worker", NOW)
        updated = self.repo.complete(item.outbox_id,"worker",DeliveryResult(DeliveryResultType.RETRYABLE_FAILURE,503,True,"HTTP_503","temporary"),NOW)
        self.assertEqual(updated.status, OutboxStatus.RETRY_WAIT)
        self.assertIsNone(updated.delivered_at)
        self.assertIsNotNone(updated.next_attempt_at)

    def test_permanent_failure_never_delivered(self):
        item, _ = self.enqueue()
        self.repo.claim_batch("worker", NOW)
        updated = self.repo.complete(item.outbox_id,"worker",DeliveryResult(DeliveryResultType.PERMANENT_FAILURE,404,False,"INVALID_WEBHOOK","deleted"),NOW)
        self.assertEqual(updated.status, OutboxStatus.FAILED_PERMANENT)
        self.assertIsNone(updated.delivered_at)

    def test_retry_exhaustion_becomes_permanent(self):
        item, _ = self.enqueue()
        current = NOW
        for index in range(6):
            self.repo.claim_batch("worker", current)
            updated = self.repo.complete(item.outbox_id,"worker",DeliveryResult(DeliveryResultType.RETRYABLE_FAILURE,500,True,"HTTP_500","temporary"),current)
            current = (updated.next_attempt_at or current) + timedelta(seconds=1)
        self.assertEqual(updated.status, OutboxStatus.FAILED_PERMANENT)

    def test_canceled_state(self):
        item, _ = self.enqueue()
        self.repo.claim_batch("worker", NOW)
        updated = self.repo.complete(item.outbox_id,"worker",DeliveryResult(DeliveryResultType.CANCELED),NOW)
        self.assertEqual(updated.status, OutboxStatus.CANCELED)

    def test_delivery_attempt_is_recorded(self):
        item, _ = self.enqueue()
        self.repo.claim_batch("worker", NOW)
        self.repo.complete(item.outbox_id,"worker",DeliveryResult(DeliveryResultType.DELIVERED,204),NOW)
        self.assertEqual(len(self.repo.list_attempts(item.outbox_id)), 1)

    def test_failed_transaction_rolls_back(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.repo.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("INSERT INTO notification_outbox(outbox_id) VALUES('invalid')")
        with self.repo.connect() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM notification_outbox").fetchone()[0],0)


if __name__ == "__main__":
    unittest.main()
