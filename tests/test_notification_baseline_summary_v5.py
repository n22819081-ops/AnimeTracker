from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from anime_tracker.modernization.schema_v5 import initialize_notification_test_database
from anime_tracker.notifications_v2 import (
    BaselineItem, ChannelPurpose, DeliveryResult, DeliveryResultType, EventType,
    NotificationOutboxRepository, SharedBaselineRepository, coverage_key, episode_key,
    render_event, week_bounds, weekly_key, weekly_summary_event,
)
from anime_tracker.notifications_v2.summaries import build_summary_sections, split_summary_lines

from notification_v2_helpers import NOW, event, message


class DeduplicationTests(unittest.TestCase):
    def test_same_episode_and_time_is_stable(self):
        self.assertEqual(episode_key(100,4,NOW),episode_key(100,4,NOW))

    def test_changed_airing_time_changes_key(self):
        self.assertNotEqual(episode_key(100,4,NOW),episode_key(100,4,NOW+timedelta(hours=1)))

    def test_same_coverage_snapshot_is_stable_and_change_differs(self):
        self.assertEqual(coverage_key(100,"mapping","snapshot",True),coverage_key(100,"mapping","snapshot",True))
        self.assertNotEqual(coverage_key(100,"mapping","snapshot",True),coverage_key(100,"mapping","snapshot-2",True))

    def test_weekly_key_separates_channel(self):
        start=NOW.date()
        self.assertEqual(weekly_key(start,ChannelPurpose.PRIVATE_TRACKER),weekly_key(start,ChannelPurpose.PRIVATE_TRACKER))
        self.assertNotEqual(weekly_key(start,ChannelPurpose.PRIVATE_TRACKER),weekly_key(start,ChannelPurpose.SHARED_ANNOUNCEMENT,True))


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=Path(self.temp.name)/"baseline.db"
        initialize_notification_test_database(self.db)
        self.baseline=SharedBaselineRepository(self.db)
        self.items=(BaselineItem("one","SERIES","One"),BaselineItem("two","MOVIE","Two"))
    def tearDown(self): self.temp.cleanup()

    def test_initial_baseline_creates_no_flood(self):
        result=self.baseline.compare(self.items)
        self.assertTrue(result.baseline_established)
        self.assertEqual(result.additions,())

    def test_accept_then_detect_addition(self):
        self.baseline.accept(self.items,NOW)
        result=self.baseline.compare((*self.items,BaselineItem("three","SEASON","Three",season_number=2)))
        self.assertEqual([item.inventory_identity for item in result.additions],["three"])

    def test_partial_scan_and_temporary_outage_do_not_remove(self):
        self.baseline.accept(self.items,NOW)
        self.assertEqual(self.baseline.compare((),complete=False).removals,())

    def test_recovered_complete_snapshot_compares_to_last_valid_baseline(self):
        self.baseline.accept(self.items,NOW)
        self.baseline.accept((),NOW+timedelta(hours=1),complete=False)
        result=self.baseline.compare((self.items[0],),complete=True)
        self.assertEqual([item.inventory_identity for item in result.removals],["two"])

    def test_failed_delivery_does_not_advance_baseline(self):
        repo=NotificationOutboxRepository(self.db)
        item,_=repo.enqueue(event(),message(ChannelPurpose.SHARED_ANNOUNCEMENT),"shared")
        repo.claim_batch("worker",NOW)
        repo.complete(item.outbox_id,"worker",DeliveryResult(DeliveryResultType.PERMANENT_FAILURE,404),NOW)
        with self.assertRaises(ValueError): self.baseline.accept_after_delivery(item.outbox_id,self.items,NOW)
        self.assertTrue(self.baseline.compare(self.items).baseline_established)

    def test_successful_delivery_advances_baseline(self):
        repo=NotificationOutboxRepository(self.db)
        item,_=repo.enqueue(event(),message(ChannelPurpose.SHARED_ANNOUNCEMENT),"shared")
        repo.claim_batch("worker",NOW)
        repo.complete(item.outbox_id,"worker",DeliveryResult(DeliveryResultType.DELIVERED,204),NOW)
        self.baseline.accept_after_delivery(item.outbox_id,self.items,NOW)
        self.assertFalse(self.baseline.compare(self.items).baseline_established)


class WeeklySummaryTests(unittest.TestCase):
    def test_week_boundary_is_monday_utc(self):
        start,end=week_bounds(datetime(2026,8,2,23,30,tzinfo=timezone.utc))
        self.assertEqual(start.weekday(),0)
        self.assertEqual(end-start,timedelta(days=7))
        self.assertEqual(start.tzinfo,timezone.utc)

    def test_naive_time_is_rejected(self):
        with self.assertRaises(ValueError): week_bounds(datetime(2026,8,2))

    def test_empty_sections_omitted_and_formats_differ(self):
        data={"Episodes aired this week":["Episode 4"],"Open review cases":[],"New episodes added":["Episodes 4-6"]}
        private=build_summary_sections(data,ChannelPurpose.PRIVATE_TRACKER)
        shared=build_summary_sections(data,ChannelPurpose.SHARED_ANNOUNCEMENT)
        self.assertEqual([section.heading for section in private],["Episodes aired this week"])
        self.assertEqual([section.heading for section in shared],["New episodes added"])

    def test_weekly_event_uses_stable_key_and_utc_storage(self):
        data={"Episodes aired this week":["Episode 4"]}
        one=weekly_summary_event(NOW,ChannelPurpose.PRIVATE_TRACKER,data,event_id="one")
        two=weekly_summary_event(NOW+timedelta(hours=1),ChannelPurpose.PRIVATE_TRACKER,data,event_id="two")
        self.assertEqual(one.deduplication_key,two.deduplication_key)
        self.assertEqual(one.event_timestamp.tzinfo,timezone.utc)

    def test_long_summary_splits_safely(self):
        chunks=split_summary_lines((f"Item {index} "+"x"*200 for index in range(100)),max_length=1000)
        self.assertGreater(len(chunks),1)
        self.assertTrue(all(len(chunk)<=1000 for chunk in chunks))

    def test_episode_batching_single_consecutive_and_nonconsecutive(self):
        single=render_event(event("single",event_type=EventType.SHARED_EPISODES_AVAILABLE,payload={"title":"Show","episodes":[4]}),ChannelPurpose.SHARED_ANNOUNCEMENT)
        consecutive=render_event(event("range",event_type=EventType.SHARED_EPISODES_AVAILABLE,payload={"title":"Show","episodes":[4,5,6]}),ChannelPurpose.SHARED_ANNOUNCEMENT)
        split=render_event(event("split",event_type=EventType.SHARED_EPISODES_AVAILABLE,payload={"title":"Show","episodes":[4,6]}),ChannelPurpose.SHARED_ANNOUNCEMENT)
        self.assertIn("Episode 4",single.body)
        self.assertIn("Episodes 4-6",consecutive.body)
        self.assertIn("Episodes 4, 6",split.body)


if __name__ == "__main__": unittest.main()
