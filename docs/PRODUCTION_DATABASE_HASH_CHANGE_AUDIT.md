# Production Database Hash Change Audit

## Conclusion

The hash changed because the verified backup procedure intentionally wrote one operational row to `backup_audit` after it completed and verified the pre-audit snapshot. No logical business data changed. The current production database is intact and safe to continue using; restoration is not recommended.

Milestone 9 was not started. This audit did not write either database, access Jellyfin media, send Discord messages, change Task Scheduler, or invoke the Storage Checker.

## Compared States

| State | SHA-256 | Role |
|---|---|---|
| Original live pre-audit file | `2636A1088980CF4C939660401BF3A7FB0EB61E15060227293204CAA7777ED148` | Hash recorded before backup; exact file was not retained |
| Verified online-backup snapshot | `7534430EB5AD6B391807F5D2C56844DFF38636C38F72A62CE22D926D4F3AD825` | Complete pre-audit logical state |
| Current post-audit database | `686BE777398D98800DB468ABB7BFA4553323850292A8F69794A8256341A9A181` | Snapshot state plus one audit row |

The snapshot manifest and database hash verify successfully, and its recorded `integrity_check` result is `ok`. The online-backup destination is a logically equivalent SQLite file, not a byte-for-byte copy of the original live file, so its physical SHA-256 differs from the recorded original pre-audit hash.

## Exact Logical Change

All 74 tables were exported canonically and compared independent of row order and SQLite page layout. Seventy-three tables are identical. Only `backup_audit` changed, from four rows to five.

The inserted row is:

- `backup_id`: `backup-10a91919638945ca819bf61245e5d502`
- `reason`: `PRE_M8_ACCEPTANCE_FIX`
- `created_at`: `2026-08-02T07:20:13.758006+00:00`
- `path_reference`: `20260802-072013-pre-m8-acceptance-fix`
- `database_sha256`: `7534430EB5AD6B391807F5D2C56844DFF38636C38F72A62CE22D926D4F3AD825`
- `integrity_result`: `ok`
- `manifest_sha256`: `A459EA1B81E77D94E6F9A4B8B7FFB4B706B23009D23D0B6BD33F60B09F7011FC`

This is expected operational metadata, backup history, and its associated timestamp. `ModernBackupManager.create()` takes and verifies the snapshot first, then opens the live database and commits this row. Therefore the backup procedure did write to production, by design.

The normalized digest of all tables except `backup_audit` is identical in both states:

`593E3D839F72B9B910927D478808B734DB75F72E9DDFDFA0EA13707C096DBE01`

## Schema And Physical State

- Logical schema: identical, digest `086A7DDFB80AA1FB24924B07271F13A35FCEA488E7AAA56F9159B5726AC66ECB`
- Objects: 74 tables, 25 indexes, no triggers, and no views in both states
- Index definitions: identical
- `user_version`: 0 in both states
- Encoding/page size/page count: UTF-8 / 4096 / 2161 in both states
- Freelist: 5 pages in both states
- Auto-vacuum: disabled in both states
- Journal mode: DELETE in both states
- Connection settings: cache size -2000, locking mode normal, synchronous 2, secure-delete 0, and WAL autocheckpoint 1000 in both reads
- Application ID: 0 in both states
- WAL files: absent in both states
- Journal files: absent after both committed states

WAL consolidation or checkpointing did not contribute. No VACUUM, page-count change, freelist change, schema migration, or index rebuild occurred.

Comparing the online-backup artifact to current production changes only pages 1, 539, and 540. Page 539 is the `backup_audit` table root and page 540 is its automatic primary-key index. Page 1 contains the SQLite header and schema page.

The backup artifact has schema cookie/file-change counter 1/1, while current production has 117/431. This is a physical-header difference caused by creating the online-backup destination plus subsequent live transactions, not a logical schema difference. An INSERT does not change the logical schema. Because the exact original live pre-audit file was not retained, its page-one counters cannot be directly compared; the recorded original hash alone cannot reconstruct them.

## Business Verification

| Invariant | Pre | Post | Result |
|---|---:|---:|---|
| Active titles | 69 | 69 | Identical |
| Archived/orphaned records | 421 | 421 | Identical |
| Shared announcement baselines | 1,312 | 1,312 | Identical rows |
| Genuine open review cases | 8 | 8 | Identical rows |
| Media server mappings | 1 | 1 | Identical rows |
| Jellyfin folder mappings | 1 | 1 | Identical rows |
| Mapping history | 1 | 1 | Identical rows |
| Rejections | 11 | 11 | Identical rows |
| AniList media cache | 69 | 69 | Identical rows |
| Media titles | 340 | 340 | Identical rows |
| Credential references | 2 | 2 | Identical and disabled |
| Notification events/outbox/attempts | 0 | 0 | Nothing delivered |
| Shared announcement deliveries | 0 | 0 | Nothing delivered |

The shared baseline table's canonical digest is unchanged, so no baseline advanced. Mapping, rejection, title, cache, tracking-state, status-history, credential, and notification table digests are unchanged. `cutover_audit` remains empty, `cutover_state` remains `PENDING_APPROVAL`, and `migration_state` remains `MIGRATED_PENDING_CUTOVER`.

Both databases return `ok` from `PRAGMA integrity_check`. `PRAGMA foreign_key_check` returns zero violations for both.

## GUI Write Audit

Opening the production GUI reads the database and profile. It does not write a last-opened time, selected page, geometry, cache-access time, health result, or diagnostic result to SQLite. Health checks use read-only connections. Cover downloads, when enabled, write only image files in the profile cache.

The GUI `closeEvent` does rewrite profile JSON files. After the backup, a GUI close at 15:11 UTC:

- added the three new notification event-generation settings with value `false`;
- persisted the Upcoming title-column width as 289 instead of 100;
- rewrote `bootstrap.json` with byte-identical content.

Those external JSON writes did not affect the SQLite hash. Last selected page and window geometry values did not change in this comparison. The acceptance smoke itself used a non-saving close path, but a later normal GUI close produced the profile-file updates above.

## Recommendation

Keep the current database and retain the verified backup. No restoration is justified because the only logical database change is the expected successful-backup audit entry. A future improvement could record backup completion in a separate operational log when byte-stable production database hashes are desired, but removing the current audit row would discard valid backup history and is not recommended.

## Separate Legacy Observation

The legacy database changed after the earlier Milestone 8 hash was recorded: its SHA-256 is now `69763FC9EC883096041C6EDEDD9399B4697EBC650A48D07BA87879C787B3782E`, with a last-write time of 14:03:04 UTC. The existing legacy log explains this: its already-configured scheduled task ran from 10:00:01 through 10:03:05 local time today, made its scheduled backup and status updates, and sent its configured Discord summary. This occurred before this audit and was not triggered by it. No Task Scheduler configuration was changed.

That legacy activity is independent of the modern database comparison: the modern database remained at `686BE777398D98800DB468ABB7BFA4553323850292A8F69794A8256341A9A181` throughout this audit. No automatic restoration or other corrective action was taken.

The machine-readable normalized comparison is in `docs/PRODUCTION_DATABASE_HASH_CHANGE_AUDIT.json`.
