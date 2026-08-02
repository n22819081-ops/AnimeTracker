# Milestone 4 Verification

## Scope

Milestone 4 adds only the modern transient read-only server inventory, tests, output protection for the Anime root, and documentation. It does not replace or call the legacy scanner; write the production or prototype databases; scan live media; match AniList titles; change workflow/review state; deliver Discord or Windows notifications; alter Task Scheduler; invoke Storage Checker; or connect the modern service to the GUI or scheduled check.

Project version remains `0.1.0`, following the existing pre-release milestone convention.

## Implementation

- `models.py`: immutable roots, root outcomes, diagnostics, items, seasons, specials, files, counters, and snapshots, plus a Milestone 2 fact adapter.
- `parser.py`: conservative season, episode, multi-episode, movie, OVA/ONA/special, sidecar, extra, extension, and year parsing.
- `service.py`: deterministic `scandir`/`stat` traversal, case-insensitive deduplication, symlink/junction avoidance, cancellation, partial results, stable item IDs, and unchanged-file reuse.
- No schema version or migration was added. Inventory remains in memory; persistence and production cutover remain Milestone 8 work.

## Test Results

Full command:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

- Collected tests: 407
- Passed tests: 407
- Additional unittest subtests: 27 passed
- Failed: 0
- Skipped: 0
- Duration: 9.24 seconds
- Existing Milestone 3 tests retained: 358
- New Milestone 4 tests: 49

Inventory-specific command:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests\test_server_inventory_parser.py tests\test_server_inventory_service.py tests\test_server_inventory_safety.py tests\test_server_inventory_compatibility.py
```

- Passed: 49
- Failed: 0
- Skipped: 0
- Duration: 0.32 seconds

Source and test compilation passed with `python -m compileall -q src tests`.

## Compatibility And Database Verification

- All 69 active legacy rows remained byte-for-value equivalent through typed adaptation before and after a temporary inventory scan.
- Production DB SHA-256 remained `52D2F8D5E1365A655CDB915A6357822EEF21D8D226797A0EE791D03491D4B2A7`.
- Original v1 prototype SHA-256 remained `239B0F263068E317C13B71541BD67C8DA6F2C2C8385CD45A6D326AB5DB1CB014`.
- Ignored v3 copy SHA-256 remained `7C05914D44B38A3972A75A205D9441CD1E8D94656BB7FC2829D83F9BF72EB5BC`.
- Production, v1, and v3 databases each reported `PRAGMA integrity_check = ok` and zero foreign-key violations.
- No schema v4 was created and no migration ran.

## Safety Verification

- Automated scans used temporary directories only. No `I:` root was opened by Milestone 4 verification.
- Static tests find no file write/delete/move calls and no SQLite, HTTP, subprocess, GUI, notification, or scheduler dependencies in the inventory package.
- The output guard now protects TV, Movies, and Anime roots.
- No Discord webhook was called and no webhook value was read or exposed.
- No Task Scheduler command or task operation occurred.
- All 8 Storage Checker files match the verified backup manifest; mismatches: 0.
- The separate Storage Checker was not imported, executed, or modified.
- Hidden legacy GUI smoke used a temporary database copy: 69 model rows, 69 tree rows, 69.28 ms construction.
- The pre-change Git rollback bundle is verified at `modernization_backups\20260802-milestone4-prechange`; SHA-256 `2E8B2B3BE58FC6CD4E4DF55C3B82FC2F62953B44B8F384BBDFB0EC04BB908B01`.

## Performance

The temporary synthetic baseline measured 1.3111 ms median for 12 files, 36.1291 ms median for a representative 360-file multi-season fixture, 1,608.7465 ms for a cold 4,800-file scan, and 431.8772 ms for its incremental rescan with all 4,800 parsed observations reused. Cancellation returned in 18.0915 ms after 178 observed files. Peak traced memory was 4.0107 MiB. Full methodology is in `MILESTONE_4_PERFORMANCE.md`.

## Known Limitations

- Absolute anime numbering, disc-order semantics, split-cour identity, edition semantics, and ambiguous numberless regular-season media remain unrecognized evidence.
- File fingerprints use normalized path, size, and nanosecond modification time; directory enumeration remains necessary on every scan.
- Symlinks and junctions are intentionally skipped rather than treated as alternate library roots.
- Read-only Jellyfin API discovery is optional and deferred.
- The inventory has no persistence, production UI, scheduler, notification, matching, or workflow integration.

Milestone 5 was not started. GUI integration remains Milestone 7. Scheduling and production cutover remain Milestone 8.
