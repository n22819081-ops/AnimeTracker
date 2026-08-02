# Milestone 8 Verification

## Automated Tests

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pytest -q
```

Final result: 633 passed, 0 failed, 0 skipped, and 47 subtests passed in 35.40 seconds.

## Production Results

- Profile: `C:\AnimeTracker\production_profile`
- Pre-cutover backup: `C:\AnimeTracker\modernization_backups\20260802-062240-pre-production-cutover`
- Milestone 7 source bundle SHA-256: `DB0A16DADB5BA168FBB1BC79D7F26855A492583DD0655A75EE23AF1A9441BD49`
- Legacy database pre/post SHA-256: `52D2F8D5E1365A655CDB915A6357822EEF21D8D226797A0EE791D03491D4B2A7`
- State: `MIGRATED_PENDING_CUTOVER`
- Schema/integrity: 6 / ok
- Active/archived/baseline: 69 / 421 / 1,312
- Mappings/rejections/candidates: 1 / 11 / 27
- Foreign-key violations/unexplained loss: 0 / 0
- AniList baseline: 69 succeeded, 0 failed, no events
- Inventory: complete, 587 items, 12,335 files, 10,843 media files
- Matching: 13 suggestions, 0 auto-confirmed, 8 genuine open reviews
- Notifications: stage 1, baseline preview pending, 0 pending outbox, delivery disabled
- Credentials: 2 separate DPAPI references migrated after explicit approval; legacy JSON retained; delivery disabled
- Scheduled command: SUCCESS in disabled-stage validation; task not installed
- Backup/restore: verified; restore tested against disposable profile
- Comparison: 69 records, 63 equivalent, 6 uncertainty preserved, 0 possible migration errors
- Cutover: pending explicit approval

The legacy task remains Ready. No production Discord send, Task Scheduler change, media modification, Storage Checker invocation, package, installer, or Milestone 9 work occurred.

## Acceptance-Fix Addendum

User acceptance exposed a case mismatch between lowercase `media_titles.title_type` values and uppercase GUI repository predicates. The correction is documented in `MILESTONE_8_ACCEPTANCE_FIXES.md` and `PRODUCTION_METADATA_BINDING.md`.

- Required pre-fix production database SHA-256: `2636A1088980CF4C939660401BF3A7FB0EB61E15060227293204CAA7777ED148`
- Verified backup: `production_profile/backups/20260802-072013-pre-m8-acceptance-fix`
- Backup database SHA-256: `7534430EB5AD6B391807F5D2C56844DFF38636C38F72A62CE22D926D4F3AD825`
- Post-backup-audit database SHA-256: `686BE777398D98800DB468ABB7BFA4553323850292A8F69794A8256341A9A181`
- Integrity and active/archived/baseline counts remained `ok` and 69/421/1,312.
- Actual-profile smoke: 69/69 titles, 8/8 reviews, 69/69 franchise rows, and 69/69 coverage rows named.
- Full acceptance suite: 643 passed, 0 failed, and 47 subtests passed in 32.67 seconds.

The actual-profile smoke was read-only and did not save settings. Checkbox persistence was validated against a verified production-profile copy. No notification was delivered.
