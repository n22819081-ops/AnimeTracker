# Milestone 1 Verification

## Scope

Milestone 1 covers backup, Git, integrity inventory, schema design, a copy-only migration prototype, reconciliation, safety documentation, and tests. It does not introduce PySide6, switch databases, contact AniList, send Discord messages, or scan Jellyfin media.

## Freeze And Backup

- No `scheduled_check.lock` was present.
- The restricted environment could not read Win32 process command lines or export/query the scheduled task. These permission failures are recorded and do not invalidate the file/database checkpoint.
- No unrelated Python process was terminated.
- Canonical backup root: `C:\AnimeTracker\Modern Anime Tracker\modernization_backups\20260801-230906-verified`
- Manifest: `C:\AnimeTracker\Modern Anime Tracker\modernization_backups\20260801-230906-verified\backup_manifest.json`
- Manifest entries: 241 meaningful files; generated `__pycache__` and `.pyc` files are excluded.
- SQLite databases verified: 179 of 179 passed `PRAGMA integrity_check`.
- Live database pre-backup SHA-256: `52D2F8D5E1365A655CDB915A6357822EEF21D8D226797A0EE791D03491D4B2A7`
- Byte-copy SHA-256: `52D2F8D5E1365A655CDB915A6357822EEF21D8D226797A0EE791D03491D4B2A7`
- SQLite online-backup SHA-256: `F2AD335C8B82602FA9FAF874EEB250BBDC6BF67FD5926FDEAB4406C68E872BB6`
- Task Scheduler XML export: unavailable due access restrictions; construction scripts are preserved.

The first checkpoint at `20260801-224532` is retained for audit history. An initial unrestricted pytest discovery updated two copied test-cache `.pyc` files in that checkpoint, causing two manifest mismatches while leaving source and databases unchanged. The canonical checkpoint was reconstructed from the unchanged first snapshot, excludes generated caches, and has zero manifest verification errors.

## Git Baseline

- Repository initialized at `C:\AnimeTracker`.
- Baseline commit: `2e2f05982526acbb75ba4f5c742697017593c47a`
- Baseline tag: `legacy-baseline-before-modernization`
- Live data, secret JSON, logs, backups, modernization backups, migration prototypes, virtual environment, generated exports/builds, locks, and the separate Storage Checker are ignored.
- Only blank webhook fields exist in the committed configuration template.

## Legacy Baseline

- Legacy tests: 146 passed plus 12 subtests in 4.98 seconds.
- Source imports: passed.
- Read-only database open: passed.
- Live database integrity: `ok`.
- Hidden legacy GUI smoke test against a verified database copy: passed with 69 rows.
- GUI construction: 54.57 ms total; UI build 8.77 ms; table population 1.85 ms.
- No live network service or Jellyfin root was contacted.

## Prototype Migration

- Source: exact byte-copy database under the modernization backup.
- Destination: ignored `Modern Anime Tracker\migration_test\anime_tracker_modern_v1.db`.
- Modern schema version: 1.
- Destination integrity check: `ok`.
- Foreign-key violations: 0.
- Unexplained source-row loss: 0 tables.
- Active tracked media: 69.
- Active AniList media: 69.
- Active server mappings: 1.
- Active rejected decisions: 11.
- Active candidates: 14.
- Active status-history rows: 153.
- Announcement baseline rows: 1,312.
- Archived uncertain/orphaned records: 421.
- Active legacy payloads retained: 69 of 69.

The 421 archived rows are exactly 92 server mappings, 8 rejected matches, 100 candidates, and 221 history rows with no active owner. They were not deduplicated or reassociated.

## Secret And Media Safety

- Real webhook values were not printed, logged, committed, report-exported, or test-sent.
- The prototype does not read the notification JSON.
- No Jellyfin media root was scanned or opened for writing.
- The separate Storage Checker was copied into the immutable backup but was not executed or modified.
- Output guards reject both Jellyfin roots and the Storage Checker.

## Known Uncertainties

- Orphan ownership cannot be proven from the legacy database and requires manual review.
- Legacy folder mappings without an explicit `Season N` scope remain unspecified and open review cases.
- Legacy `On Server` cannot establish episode completeness and migrates to `UNKNOWN_COVERAGE`.
- Stored path existence was deliberately not checked during Milestone 1.
- Scheduled-task XML and runtime state remain unverified because the current execution identity receives Access Denied.

## Completion Gate

- Full suite collected: 159 tests.
- Passed: 159 tests plus 12 subtests.
- Failed: 0.
- Skipped: 0.
- Duration: 4.96 seconds.
- Source compilation: passed.
- Live database post-change SHA-256: `52D2F8D5E1365A655CDB915A6357822EEF21D8D226797A0EE791D03491D4B2A7` (unchanged).
- Storage Checker aggregate SHA-256: `552F26360C1D174C92AD8765C81BE416D6AD25CF6F4C92739F696E1088EE0828` (unchanged).
- Prototype integrity: `ok`; foreign-key violations: 0.
- Webhook URLs found in Milestone artifacts: 0.
- Git implementation commit is reported in the completion response because a commit cannot include its own final hash.
