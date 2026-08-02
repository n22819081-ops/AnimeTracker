# Legacy Performance Baseline

Measured on August 1, 2026 using the existing Python environment and a verified database copy. No AniList, Discord, Jellyfin, or Storage Checker operation was performed.

| Measurement | Result |
|---|---:|
| `import anime_tracker.app` median, 5 fresh processes | 232.07 ms |
| Database open plus current-schema check | 1.679 ms |
| Simulated startup database reads | 1.605 ms |
| Startup SQLite connections | 5 |
| Startup SQL statements | 43 |
| Tracked rows loaded | 69 |
| Open plus tracker-table load median, 20 runs | 0.569 ms |
| Candidate rows loaded | 114 in 0.340 ms |
| Status-history rows loaded | 374 in 0.577 ms |
| Hidden main-window construction against verified DB copy | 54.57 ms |
| `_build_ui` portion | 8.77 ms |
| Initial table population | 1.85 ms |
| Legacy test suite | 146 passed plus 12 subtests in 4.98 s |

## GUI Measurements

Tk initialization is blocked under the restricted sandbox identity, but succeeds under the normal user context. The GUI measurement used a hidden window and a disposable verified database copy, then closed immediately. It did not enter the event loop, contact services, or write the live database.

## Interpretation

SQLite reads are not a startup bottleneck at the current data size. The major known operational costs remain sequential AniList requests and recursive Jellyfin scans, but neither live service was exercised during this milestone.
