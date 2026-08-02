"""Synthetic Milestone 6 performance baseline. No network or live data access."""

from __future__ import annotations

import json
import statistics
import tempfile
import threading
import time
from pathlib import Path

from anime_tracker.modernization.schema_v5 import initialize_notification_test_database
from anime_tracker.notifications_v2 import (
    BaselineItem, ChannelPurpose, NotificationOutboxRepository, SharedBaselineRepository,
    weekly_summary_event,
)
from notification_v2_helpers import NOW, event, message


def measure(operation, repetitions=5):
    samples=[]
    for _ in range(repetitions):
        started=time.perf_counter(); operation(); samples.append((time.perf_counter()-started)*1000)
    return statistics.median(samples)


def main():
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/"performance.db"
        initialize_notification_test_database(path)
        repo=NotificationOutboxRepository(path)
        single=measure(lambda: repo.enqueue(event("single"),message(),"private"),7)

        started=time.perf_counter()
        for index in range(1000):
            repo.enqueue(event(f"bulk-{index}",event_id=f"bulk-event-{index}"),message(),"private")
        enqueue_1000=(time.perf_counter()-started)*1000

        started=time.perf_counter()
        for index in range(1000):
            repo.enqueue(event(f"bulk-{index}",event_id=f"repeat-event-{index}"),message(),"private")
        dedupe_1000=(time.perf_counter()-started)*1000

        claim_100=measure(lambda: repo.claim_batch(f"claim-{time.perf_counter_ns()}",NOW,limit=100),3)

        summary_data={
            "Episodes aired this week":[f"Synthetic Anime {index}: Episode {index%12+1}" for index in range(69)],
            "Episodes missing from server":[f"Synthetic Anime {index}: Episode 4" for index in range(12)],
            "Open review cases":[f"Synthetic Anime {index}" for index in range(5)],
        }
        summary=measure(lambda: weekly_summary_event(NOW,ChannelPurpose.PRIVATE_TRACKER,summary_data,event_id="benchmark"),100)

        baseline=SharedBaselineRepository(path)
        rows=tuple(BaselineItem(f"item-{index}","SEASON",f"Synthetic Anime {index}",season_number=index%12+1) for index in range(1312))
        baseline_1312=measure(lambda: baseline.compare(rows),10)

        contention_db=Path(folder)/"contention.db"; initialize_notification_test_database(contention_db)
        contention_repo=NotificationOutboxRepository(contention_db)
        for index in range(100): contention_repo.enqueue(event(f"race-{index}",event_id=f"race-event-{index}"),message(),"private")
        barrier=threading.Barrier(2); claimed=[]
        def worker(name):
            barrier.wait(); claimed.extend(contention_repo.claim_batch(name,NOW,limit=100))
        started=time.perf_counter(); threads=[threading.Thread(target=worker,args=(name,)) for name in ("one","two")]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        contention=(time.perf_counter()-started)*1000

        print(json.dumps({
            "enqueue_one_ms_median":round(single,4),
            "enqueue_1000_ms":round(enqueue_1000,4),
            "deduplicate_1000_ms":round(dedupe_1000,4),
            "claim_100_ms_median":round(claim_100,4),
            "weekly_summary_69_ms_median":round(summary,4),
            "compare_1312_baseline_rows_ms_median":round(baseline_1312,4),
            "two_worker_contention_100_items_ms":round(contention,4),
            "two_worker_total_claims":len(claimed),
            "two_worker_unique_claims":len({item.outbox_id for item in claimed}),
        },indent=2,sort_keys=True))


if __name__=="__main__": main()
