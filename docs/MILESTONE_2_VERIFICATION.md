# Milestone 2 Verification

## Scope

Milestone 2 adds only the persistence-neutral domain package, its tests, and documentation. It does not wire the new engine into the legacy Tkinter application, change schema version 1, replace either database, scan Jellyfin, contact AniList, deliver Discord messages, alter scheduling, invoke the Storage Checker, or begin Milestone 3.

## Domain Package

- `enums.py`: independent provider, workflow, presence, review, media, mapping, override, rejection, relation, and transition vocabularies.
- `models.py`: immutable typed identities, tracking state, inventory evidence, coverage, mappings, reviews, overrides, decisions, archive bundles, and events.
- `coverage.py`: deterministic episode normalization and presence rules for airing, finished, movie, and special content.
- `status_engine.py`: explicit precedence with structured reasons, warnings, and visible override effects.
- `mappings.py` and `reviews.py`: explicit season scope, shared-folder support, durable scoped rejection, and genuine-conflict review generation.
- `overrides.py`: active/superseded/expiring override evaluation with no implicit clock in status decisions.
- `archive.py`: non-destructive archive/restore preserving related records.
- `transitions.py`: typed comparisons with no events for unchanged snapshots.
- `legacy_adapter.py`: row-only conservative conversion with no SQLite query dependency.

## Regression Results

Full command:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

- Collected tests: 249
- Passed tests: 249
- Additional unittest subtests: 12 passed
- Failed: 0
- Skipped: 0
- Duration: 5.69 seconds
- Existing Milestone 1 tests retained: 159
- New Milestone 2 tests: 90
- Domain source compilation: passed

The new matrix covers status separation, airing and finished coverage, movies, specials/OVAs, season-scoped shared folders, mapping history, rejection scopes, review boundaries, overrides, archive/restore preservation, all transition classes, unchanged-event deduplication, legacy conversion, and dependency/write safety.

## Legacy Compatibility

- All 69 active rows from the verified read-only backup adapted successfully.
- All 69 AniList identities remained unique and represented.
- Legacy `On Server` is preserved by an explicit legacy override; server coverage remains `UNKNOWN_COVERAGE`.
- Legacy `Not Found` maps to normal `NOT_FOUND`, not review.
- Legacy review and missing-path evidence map conservatively to typed review cases.
- All 421 prototype archived/orphan records remain representable and marked for manual review.
- Prototype integrity: `ok`; foreign-key violations: 0.
- No row was reassigned, merged, invented, deleted, or migrated into production.

## Safety And Hashes

- Live database pre-change SHA-256: `52D2F8D5E1365A655CDB915A6357822EEF21D8D226797A0EE791D03491D4B2A7`
- Live database post-change SHA-256: `52D2F8D5E1365A655CDB915A6357822EEF21D8D226797A0EE791D03491D4B2A7`
- Verified-backup manifest: 241 entries, 0 errors after verification.
- Storage Checker checkpoint comparison: 8 files, 0 mismatches; prior aggregate SHA-256 remains `552F26360C1D174C92AD8765C81BE416D6AD25CF6F4C92739F696E1088EE0828`.
- Hidden legacy GUI smoke: passed against a temporary database copy; 69 model rows and 69 tree rows; 69.51 ms construction.
- GUI smoke stubbed logging and notification config. It did not read a webhook or run the main loop.
- Static safety tests reject GUI, Requests/network, Discord, SQLite, scanner, subprocess, notification, and scheduler dependencies in the domain package.
- No live Jellyfin scan occurred and no media root was opened or modified.
- No Discord webhook was called.
- No AniList request was made by the automated tests.
- The separate Storage Checker was not imported, invoked, or modified.

## Performance

- One decision: median 3.8936 microseconds.
- All 69 current records: median 0.2323 ms.
- 1,000 synthetic records: median 3.8425 ms.

Full method and ranges are in `MILESTONE_2_PERFORMANCE.md`.

## Schema Decision

No schema version 2 migration was created. The Milestone 2 layer is intentionally independent of persistence, and changing the version 1 prototype would add migration risk without serving this milestone. The domain/schema vocabulary difference is documented for a future transactional persistence milestone.

## Known Uncertainties

- Legacy `On Server` evidence cannot prove episode coverage; it remains an explicit preserved override with `UNKNOWN_COVERAGE`.
- The 421 ownerless legacy child rows cannot be safely reassigned without new evidence.
- Specials and OVAs require a confirmed mapping decision when parent or scope is ambiguous.
- Provider airing counts, Jellyfin inventories, stable Jellyfin IDs, and relation graphs are future service-layer inputs; Milestone 2 deliberately does not fetch them.
- Cancelled and otherwise inconsistent provider states use a documented deterministic fallback with a warning until product policy is refined.

Milestone 3 has not begun.
