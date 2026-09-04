# Milestone 6 Verification

## Scope

Milestone 6 adds the isolated notification-v2 package, schema v5 for disposable databases, tests, benchmarks, and documentation. It does not change production notification behavior, GUI, scheduler, packaging, live persistence, or application version. Version remains `0.1.0`.

## Tests

Full command:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

- Collected: 560 tests
- Passed: 560
- Additional unittest subtests: 47 passed
- Failed: 0
- Skipped: 0
- Duration: 17.25 seconds
- Existing Milestone 5 tests retained: 495
- Milestone 6 tests added: 65

Compilation passed with `python -m compileall -q src tests`. Notification-specific tests use injected HTTP mocks and temporary databases only.

## Reliability

- Two simultaneous workers claimed 100 total and 100 unique outbox rows.
- Completion rejects the wrong worker. Expired leases recover normally.
- Failed sends have no delivered timestamp. Retryable failures enter `RETRY_WAIT`; exhausted/permanent failures enter `FAILED_PERMANENT`.
- Event plus channel deduplication separates private/shared delivery while eliminating repeats within each purpose.
- Suppression supports AniList ID, event type, channel, date range, temporary snooze, and explicit clearing.
- Discord 429/500/502/503/504, timeout, and connection failures are retryable. HTTP 400/401/403/404 are permanent.
- Silent shared payloads contain integer `flags: 4096` in every split JSON body; non-silent payloads omit it.

## Compatibility And Privacy

- A disposable v4 copy migrated transactionally through schema versions 1-5 with SQLite integrity `ok` and zero foreign-key violations.
- Ignored schema-v5 copy SHA-256: `1864E562E62AC36085BA94078B25E36149C48868E3174BDE608484922CD092F4`.
- All 1,312 shared baseline rows were preserved in v2 and in the renamed v1 audit table.
- Initial empty baseline comparison creates no announcements. Partial/outage snapshots create no removals, and failed delivery cannot advance baseline.
- Manual queue and historical delivery evidence are preserved; failed legacy evidence is not reinterpreted as delivered.
- Private and shared templates, filters, credentials, history, and silent policy are separate.
- No raw webhook value is stored in SQLite, payloads, diagnostics, or logs. Production notification configuration was not opened automatically.
- Optional one-message Discord integration check: not run.
- Hidden legacy GUI smoke against a verified database copy: 69 rows, 73.64 ms construction.

## Safety

- Live database pre/post SHA-256: `52D2F8D5E1365A655CDB915A6357822EEF21D8D226797A0EE791D03491D4B2A7`.
- No live Jellyfin root was scanned and no media was modified.
- Normal automated tests sent no Discord or Windows notification.
- No Task Scheduler command or change occurred.
- All eight Storage Checker files matched the verified manifest; Storage Checker was not invoked or modified.
- Rollback bundle: `Modern Anime Tracker\modernization_backups\20260802-milestone6-prechange\milestone5-checkpoint.bundle`, SHA-256 `C4976F5F99DB3EC3C6D4CB23E5E156454AA1209952BF98741C3A0D6D3D4A836A`.

## Known Limitations

- Windows Credential Manager and DPAPI production stores remain future cutover work; only the interface and test store exist.
- Schema v5 is not connected to the legacy GUI or scheduled check.
- Per-event enqueue commits favor durability over bulk speed; a future batch API can improve throughput.
- Display-timezone configuration is deferred; weekly boundaries are UTC.
- Discord payload compaction is conservative and does not yet optimize every rich-embed layout.
