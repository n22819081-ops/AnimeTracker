# Milestone 3 Verification

## Scope

Milestone 3 adds a modern AniList service beside the unchanged legacy client. It does not change legacy GUI behavior, production scheduling, Jellyfin scanning/matching, Discord delivery, Task Scheduler, packaging, or the live database. Milestone 4 has not begun.

## Test Results

Full command:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

- Collected tests: 358
- Passed tests: 358
- Additional unittest subtests: 27 passed
- Failed: 0
- Skipped: 0
- Duration: 8.71 seconds
- Existing Milestone 2 tests retained: 249
- New Milestone 3 tests: 109
- Source compilation: passed

All normal AniList tests used injected fake HTTP sessions and sanitized fixtures. No automated test depended on live AniList availability. The optional three-ID live check was disabled and not run.

## Schema V3 Prototype

- Source v1 prototype SHA-256: `239B0F263068E317C13B71541BD67C8DA6F2C2C8385CD45A6D326AB5DB1CB014`
- Source v1 prototype unchanged: yes
- Ignored v3 copy: `C:\AnimeTracker\Modern Anime Tracker\migration_test\anime_tracker_modern_v3.db`
- V3 copy SHA-256: `7C05914D44B38A3972A75A205D9441CD1E8D94656BB7FC2829D83F9BF72EB5BC`
- Recorded versions: 1, 2, 3
- Integrity: `ok`
- Foreign-key violations: 0
- Active tracked/AniList rows: 69 / 69
- Active mappings/rejections/candidates/history: 1 / 11 / 14 / 153
- Archived/orphan records: 421

Version 2 is an explicit no-persistence-change marker for Milestone 2. Version 3 was applied transactionally only to the copied prototype. Existing row counts were unchanged.

## Service Verification

- Typed media parsing covers all requested formats, missing fields, partial dates, adult flags, schedules, and real relation IDs.
- Search covers AniList ID/URL, MAL ID, title, filters, configurable pagination/limit, deduplication, empty results, and offline title variants.
- Cache covers fresh/stale/miss/corrupt states, forced refresh, invalidation, failure retention, independent relation/schedule state, bulk reads, and test-only clear boundaries.
- Rate limits cover remaining/reset headers, positive/zero/missing/invalid retry values, bounded jitter, retry ceilings, permanent errors, cancellation, and low-capacity pacing.
- Batches cover all-success, partial, all-failure, cache-only, mixed, deduplicated, canceled, archived-excluded, persisted totals, and the 42-success/27-failure case.
- Airing comparison covers new, upcoming, delayed, changed, removed, season-started, and series-finished candidates with duplicate suppression.
- Franchise graphs preserve IDs/types/direction and support components, main chains, branches, tracked intersections, ambiguity warnings, and persisted group suggestions without server mapping.
- All 69 active legacy records accept modern typed metadata; unresolved generic relation labels retain their audit value without invented targets.

## Performance

- Fresh cache lookup: 0.4399 ms median.
- Stale cache lookup: 0.3892 ms median.
- Fixture parse: 0.0097 ms median.
- Franchise graph at current size: 0.0423 ms median.
- Persisted 69-record cache refresh: 9.1804 ms median.
- Bulk 1,000-record cache evaluation: 27.2852 ms median.

## Safety And Isolation

- Live database pre/post SHA-256: `52D2F8D5E1365A655CDB915A6357822EEF21D8D226797A0EE791D03491D4B2A7`.
- Verified backup manifest: 241 entries, 0 errors.
- Storage Checker checkpoint: 8 files, 0 mismatches; prior aggregate SHA-256 remains `552F26360C1D174C92AD8765C81BE416D6AD25CF6F4C92739F696E1088EE0828`.
- Legacy hidden GUI smoke against a temporary copy: passed with 69 model and 69 tree rows; 75.23 ms construction.
- GUI smoke stubbed logging and notification configuration.
- No full or partial Jellyfin scan occurred; no media root was opened or modified.
- No Discord webhook was called. Webhook-shaped strings found by source scan are only the preexisting fake Milestone 1 redaction fixtures.
- No Task Scheduler operation occurred.
- The separate Storage Checker was not imported, invoked, or modified.
- No production migration or modern-service cutover occurred.

## Known Limitations

- AniList does not establish trustworthy digital/Blu-ray movie availability; it remains `UNKNOWN`.
- Relation graphs cannot determine Jellyfin folders or season numbers.
- Provider schedule absence may mean no schedule or incomplete provider data; it is never converted into server coverage.
- The network refresh coordinator is deliberately sequential and conservative rather than high-concurrency.
- Cache TTLs and retry defaults are documented policy and may be tuned after production telemetry exists; Milestone 3 adds no telemetry.
- The modern service is not yet used by the legacy GUI or scheduled check.

Milestone 4 has not begun.
