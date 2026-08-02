# Server Inventory Design

## Scope

Milestone 4 adds a transient, read-only filesystem inventory behind `FilesystemInventoryService`. It discovers server facts only. It does not match titles, infer AniList identity, calculate tracker workflow, create reviews, send notifications, schedule work, or persist a snapshot.

The configured production roots are TV, Movies, and Anime under `I:\Jellyfin_Media`. They are protected output locations. Automated tests use temporary directories and no automated or manual Milestone 4 verification opens the live roots.

## Boundary

Callers provide typed `LibraryRoot` values and may provide a previous snapshot and cancellation token. The result is an immutable `ServerInventorySnapshot` containing one `RootInventory` per requested root, typed library items, season-scoped file observations, special groups, diagnostics, and counters.

The service depends only on injected `scandir` and `stat` readers. This makes permission and partial-read behavior testable without changing filesystem permissions. It contains no SQLite, HTTP, GUI, notification, scheduler, subprocess, or matching dependency.

## Discovery

- Root order, directory order, items, files, diagnostics, seasons, and special groups are sorted deterministically.
- Windows comparison paths normalize slashes, trailing separators, and case without changing original path spelling.
- Each case-insensitive path is claimed once per scan. Repeated or case-variant paths produce a diagnostic and no duplicate item.
- Symbolic links and Windows junctions are skipped. The scanner never follows a reparse-point directory into a cycle.
- Immediate directories under TV or Anime roots are library items, including empty show folders. Media inside them is traversed recursively.
- Movie folders and standalone movie files are represented as movie items.
- A stable filesystem item ID is derived from library kind and normalized path. It is not a Jellyfin ID or AniList mapping.

## Incremental Snapshots

A previous in-memory snapshot may be supplied. Files whose normalized path, size, and nanosecond modification time are unchanged reuse their parsed `InventoryFile` observation. Directories are still enumerated so additions, removals, and access failures remain visible. No cache is written to disk and a failed scan is never persisted as complete.

## Errors And Partial Results

`COMPLETE`, `EMPTY`, `PARTIAL`, `MISSING`, `INACCESSIBLE`, and `CANCELED` are distinct root outcomes. A missing root is not an empty root. `EMPTY` means the root contains no library item or standalone movie, while an empty show folder is retained as an item with no coverage. Failure to enumerate the root is inaccessible; failure below it is partial and retains successfully observed siblings. A metadata failure retains conservative filename evidence with unknown size/time. Diagnostics expose a relative path, exception type, and controlled message rather than the raw exception text.

Cancellation is checked before each root and during traversal. Completed observations are retained, the current root is marked canceled, and unstarted roots are represented as canceled without being opened.

## Safety

The implementation calls only directory enumeration, metadata stat, and path/string operations. It never opens media content and has no operation capable of creating, renaming, moving, replacing, editing, transcoding, or deleting media. The production scanner and all later-milestone integrations remain unchanged.

## Deferred Work

- Read-only Jellyfin API discovery is optional and deferred until credentials and operational policy are designed.
- Matching, season-target proposals, rejections, and review cases belong to Milestone 5.
- Notification delivery belongs to Milestone 6.
- GUI progress and cancellation wiring belongs to Milestone 7.
- Snapshot persistence, production scheduling, and cutover belong to Milestone 8.
