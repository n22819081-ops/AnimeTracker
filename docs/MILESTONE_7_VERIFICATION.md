# Milestone 7 Verification

## Automated Results

Command:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pytest -q
```

Final post-edit result: 600 passed, 0 failed, 0 skipped, and 47 subtests passed in 32.88 seconds.

Coverage includes startup/profile isolation, all 12 pages, navigation persistence, dashboard counts, sorting/search/filtering, stable updates, dialogs, franchise season scopes, review safety, coverage views, notification privacy, theme/settings persistence, worker cancellation/error/shutdown, cover fallback, exact import totals, and static production-safety boundaries.

## Profile And Import

- Active tracked titles: 69
- Archived/orphaned records: 421
- Shared announcement baselines: 1,312
- Mappings: 1
- Rejections: 11
- Candidates: 14

## Safety

The GUI used only a copied schema-v5 development database and synthetic/test scan controls. No automatic AniList request, live Jellyfin scan, media write, production webhook read/send, Task Scheduler operation, production database write, or Storage Checker invocation is present in its startup path.

- Live database pre/post SHA-256: `52D2F8D5E1365A655CDB915A6357822EEF21D8D226797A0EE791D03491D4B2A7`
- Milestone 6 rollback bundle SHA-256: `D22A36186036210488C1E2215577A8444780E891A96A88C7BEAB50F60EF8CAB4`
- Storage Checker comparison: 8 manifest files checked, 0 changed
- Modern native Windows smoke: 12 pages, clean exit
- Legacy Tkinter smoke: 69 rows, 62.55 ms construction, clean exit

## Screenshots

Redacted synthetic screenshots are under `docs\screenshots\milestone_7` for Dashboard, Currently Airing, Franchises, Matching Review, Jellyfin Coverage, Notifications, and Settings.

## Known Limitations

Milestone 7 is a parallel development interface. Live Add Anime persistence, production refresh/scan adapters, mutating review decisions, real notification delivery, scheduling, cutover, packaging, and installer changes remain disabled for Milestone 8 or later. Relation visualization is a structured tree. Cached cover loading is implemented as a service boundary, while current table cells use lightweight placeholders.
