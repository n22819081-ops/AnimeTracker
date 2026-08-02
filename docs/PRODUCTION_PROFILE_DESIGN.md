# Production Profile Design

Mutable modern data is isolated under `C:\AnimeTracker\production_profile`:

- `data\anime_tracker_modern.db`: schema-v6 modern database
- `data\credentials`: per-secret Windows DPAPI blobs after explicit migration
- `logs`: structured scheduled-run results
- `backups`: verified modern backups
- `cache\anilist` and `cache\covers`: application caches
- `diagnostics`: local and privacy-safe reports
- `execution\locks`: migration, restore, backup, scan, and scheduled-run locks
- `bootstrap.json`: activation gates and cutover state

The profile never shares SQLite connections or a writable database with the legacy tracker. It is excluded from Git. Current state is `MIGRATED_PENDING_CUTOVER` and `PENDING_APPROVAL`.
