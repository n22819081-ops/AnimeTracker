# Milestone 5 Verification

## Scope

Milestone 5 adds typed matching targets, deterministic candidate scoring, persistent mappings and decisions, season-scoped coverage, review lifecycles, schema v4 for disposable databases, tests, and documentation. It does not connect the modern layer to the legacy GUI, live database, scheduled task, Discord, or any media operation. Project version remains `0.1.0` under the existing pre-release milestone convention.

## Test Results

Full command:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

- Collected: 495 tests
- Passed: 495 tests
- Additional unittest subtests: 27 passed
- Failed: 0
- Skipped: 0
- Duration: 13.27 seconds
- Existing Milestone 4 tests retained: 407
- Milestone 5 matching tests added: 88

Matching-specific command:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_matching_candidates_v4.py tests\test_matching_persistence_v4.py tests\test_matching_reviews_coverage_v4.py tests\test_matching_safety_legacy_v4.py -q
```

- Collected and passed: 88
- Failed: 0
- Skipped: 0

Source and test compilation passed with `python -m compileall -q src tests`.

## Database And Legacy Compatibility

- Live database pre/post SHA-256: `52D2F8D5E1365A655CDB915A6357822EEF21D8D226797A0EE791D03491D4B2A7`.
- Prototype v1 remained `239B0F263068E317C13B71541BD67C8DA6F2C2C8385CD45A6D326AB5DB1CB014`.
- Prototype v3 remained `7C05914D44B38A3972A75A205D9441CD1E8D94656BB7FC2829D83F9BF72EB5BC`.
- Ignored v4 migration copy SHA-256: `16BBF34282C0DFE6FA4840CF7E51E3629C94E931C0FDD536B39BC04DAB97277A`.
- v4 reported schema versions 1-4, `PRAGMA integrity_check = ok`, and zero foreign-key violations.
- Legacy adaptation preserved 1 active mapping without inventing season scope, 11 active exact-path rejections, 14 stale historical candidates, and all 64 legacy review rows in the audit table. Five genuine reviews became active; 59 ordinary no-match rows did not.
- Orphan archives and manual On Server payloads remain unchanged and separately represented.
- Hidden legacy GUI smoke used a verified database copy: 69 model/tree rows, 74.13 ms construction.

## Behavioral Verification

- Season 1 cannot satisfy Season 2; requested season targets are generated only when that season exists.
- Three AniList IDs persist against one inventory item as independent Season 01, Season 02, and Season 00 scopes.
- Coverage reads only the confirmed scope. A shared parent folder does not imply franchise coverage.
- Movies generate from Movies inventory only and cannot be satisfied by a related TV folder.
- OVAs, ONAs, and specials may suggest Season 00, a separate series, or a movie, but require manual confirmation.
- Rejections and suppressions persist independently across restarts and inventory reorder/case normalization.
- Not on Server is a normal manual decision, creates no review, and does not prevent a future explicit mapping.
- Confirmed and broken mappings are never silently replaced. Missing paths retain mapping/history and create a typed review.
- Repeated missing scans are idempotent, stale candidates cannot be confirmed, and regeneration restores a valid confirmation path.
- Review regeneration uses stable identities and resolves only cases addressed by the decision.

## Safety Verification

- No live Jellyfin root was scanned or opened by Milestone 5 verification; all inventory was synthetic and in memory.
- No media file or folder was created, modified, moved, renamed, replaced, or deleted.
- The live database was neither migrated nor replaced.
- No Discord webhook or Windows notification was called.
- No Task Scheduler command or task change occurred.
- All 8 Storage Checker files match the verified backup manifest; mismatches: 0. Storage Checker was not invoked or modified.
- The pre-change rollback bundle is `Modern Anime Tracker\modernization_backups\20260802-milestone5-prechange\milestone4-checkpoint.bundle`, SHA-256 `A498353FCFA58318F54F35270DA66B1373D2DE991338F07FB61F11BD5584299E`.

## Known Limitations

- Automatic confirmation remains intentionally disabled; the future PySide6 review UI must collect confirmation.
- Absolute numbering is preserved but needs a future explicit absolute-to-season episode mapping table.
- Mixed-folder detection is conservative and cannot infer every release-group layout.
- Read-only Jellyfin API stable IDs are not yet integrated, so filesystem inventory IDs remain the current identity source.
- Batch candidate generation currently recomputes the snapshot fingerprint per entry; a future coordinator can cache it.
- Production persistence, GUI, notifications, scheduling cutover, and packaging remain later milestones.
