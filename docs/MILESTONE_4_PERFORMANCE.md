# Milestone 4 Performance

## Method

Measured on 2026-08-02 with Python 3.12 on temporary Windows directories. Fixtures contained zero-byte files and no network, SQLite, GUI, notification, Task Scheduler, Storage Checker, or live Jellyfin access.

- Small: median of 11 scans of one season with 12 episodes.
- Representative: median of 7 scans of 10 shows, 3 seasons each, 12 episodes per season (360 media files).
- Large: one traced scan of 50 shows, 4 seasons each, 24 episodes per season (4,800 media files).
- Incremental: one immediate rescan of the large fixture using its prior snapshot.
- Parser: median of 11 batches of 10,000 multi-episode filename parses.
- Cancellation: large fixture with a deterministic token canceled after 200 checks.

## Results

| Workload | Result |
|---|---:|
| Small fixture | 1.3111 ms median |
| Representative multi-season fixture | 36.1291 ms median |
| Large 4,800-file cold scan | 1,608.7465 ms |
| Large unchanged incremental scan | 431.8772 ms |
| Incremental file parses reused | 4,800 of 4,800 |
| 10,000 filename parses | 19.5831 ms median |
| Cancellation response | 18.0915 ms; 178 files observed |
| Large-scan peak traced memory | 4.0107 MiB |

The incremental path still enumerates and stats files so additions, removals, and access failures are not hidden. Results are a local engineering baseline, not a hardware-independent guarantee.
