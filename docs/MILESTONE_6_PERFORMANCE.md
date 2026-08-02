# Milestone 6 Performance

Measured on 2026-08-02 with Python 3.12 using `tests/benchmark_notifications_v5.py`. The harness used temporary schema-v5 databases, in-memory synthetic messages, and no HTTP, Discord, GUI, live database, Jellyfin, scheduler, or Storage Checker access.

| Workload | Result |
|---|---:|
| Enqueue one event | 1.3707 ms median |
| Enqueue 1,000 distinct events | 5,260.8473 ms |
| Deduplicate 1,000 repeated events | 1,198.1424 ms |
| Claim 100 items | 9.0247 ms median |
| Render weekly summary at 69-title scale | 0.0149 ms median |
| Compare 1,312 baseline rows | 0.4987 ms median |
| Two-worker contention over 100 items | 12.7858 ms |
| Two-worker claims | 100 total, 100 unique |

The enqueue benchmark intentionally commits each event separately, matching the safest service API. A future coordinator may add a transactional bulk-enqueue method to reduce the 1,000-event cost without changing deduplication or durability.
