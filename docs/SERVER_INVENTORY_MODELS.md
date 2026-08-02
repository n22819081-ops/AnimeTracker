# Server Inventory Models

## Snapshot Types

- `LibraryRoot`: caller-owned label, path, and `TV` or `MOVIE` library kind.
- `ServerInventorySnapshot`: ordered root results, aggregate counters, and cancellation state.
- `RootInventory`: root configuration, explicit scan status, items, and diagnostics.
- `InventoryStatistics`: roots/directories/files/media observed, reused file parses, and duplicates skipped.
- `ScanDiagnostic`: typed code, root label, relative path, error type, and controlled explanation.

## Content Types

- `InventoryLibraryItem`: filesystem identity, original and normalized path, folder title, conservative year, seasons, specials, movie files, and unrecognized media.
- `InventorySeason`: an explicit numbered season and its parsed files. Empty season folders remain represented, and season numbers are never collapsed across a show.
- `InventorySpecialGroup`: explicit `SPECIAL`, `OVA`, or `ONA` directory evidence and files. It does not imply an AniList relationship or final mapping target.
- `InventoryFile`: original/relative/normalized path, size/time fingerprint, classification, season, zero or more episode numbers, and optional special kind.

An `InventoryFile` may hold multiple episode numbers for a multi-episode media file. Unknown-numbered media remains present as `UNRECOGNIZED_MEDIA`; it is never counted as a known episode.

## Domain Adapter

`InventoryLibraryItem.to_domain_model()` supplies the existing Milestone 2 `ServerLibraryItem`, `ServerSeason`, `ServerEpisode`, and `ServerMovie` facts. Explicit specials become Season 00 domain evidence while retaining `is_special=True`. The adapter does not call coverage or status rules.

The inventory models intentionally contain no AniList ID, franchise relation, manual match, rejection, override, archive state, tracker status, review status, server status, digital availability, or notification state.
