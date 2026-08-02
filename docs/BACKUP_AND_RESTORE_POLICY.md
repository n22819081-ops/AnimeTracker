# Backup And Restore Policy

## Backup Creation

- Use SQLite's online backup API for every database checkpoint.
- When the application is confirmed idle, also create a byte-for-byte baseline copy.
- Record SHA-256, size, UTC creation time, source role, application version, and schema version in a JSON manifest.
- Run `PRAGMA integrity_check` and `PRAGMA foreign_key_check` against copies, never by changing the live database.
- Treat a backup as complete only when its manifest and database checks succeed.
- Never place a backup destination inside either Jellyfin media root or the Storage Checker.

## Retention Design

- Keep the newest 10 routine backups.
- Keep one daily backup for 14 days.
- Keep one weekly backup for 12 weeks.
- Keep modernization checkpoints indefinitely until version 1 is accepted.
- Never automatically delete the original modernization baseline.
- Retention planning produces a review list only. Deletion requires a separate confirmed maintenance operation.

Existing backups are not subject to deletion during modernization Milestone 1.

## Restore Procedure

1. Stop Anime Tracker and confirm no scheduled lock or known writer exists.
2. Back up the current database before restoring anything.
3. Verify the selected manifest and SHA-256 values.
4. Open the selected database read-only and run integrity and foreign-key checks.
5. Restore to a temporary sibling path.
6. Validate schema version and expected row counts.
7. Replace the application database only during an explicitly approved maintenance window.
8. Start the application without AniList, Jellyfin, or Discord operations and validate representative records.
9. Retain both pre-restore and restored checkpoints until acceptance.

## Failure Rules

A failed copy, hash mismatch, integrity error, foreign-key error, or count mismatch aborts restore. No partial restore may replace the active database.
