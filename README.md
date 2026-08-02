# Anime Tracker

Anime Tracker is a local Windows desktop app for tracking anime you want to add to a Jellyfin server. It uses AniList public GraphQL queries for metadata and stores local tracking state in SQLite.

## Modernization Status

Modernization Milestones 1 through 7 establish verified backups, reconciled copy-only migration data, typed domain/status rules, modern AniList and inventory services, persistent season-scoped matching, a transactional notification outbox, and a separate PySide6 development GUI. The modern GUI uses a disposable profile and does not replace the live database or production notification behavior.

Milestone documentation is under `docs/`. The disposable prototype is created under ignored `migration_test/`, and the immutable checkpoint is under ignored `modernization_backups/`.

The separate `jellyfin storage checker` is a different product. It is excluded from Git and modernization and must not be invoked or modified by Anime Tracker.

The app scans Jellyfin folders read-only. It never renames, moves, modifies, replaces, or deletes anything in your media folders.

The modern inventory also recognizes the protected Anime root at `I:\Jellyfin_Media\Anime`. Production cutover remains deferred to Milestone 8.

## Install

From PowerShell:

```powershell
.\Install.ps1
```

This creates a local virtual environment and installs Python dependencies.

## Run

```powershell
.\Run-AnimeTracker.ps1
```

Or directly:

```powershell
.\.venv\Scripts\python.exe -m anime_tracker.app
```

### Modern Development GUI

```powershell
.\Run-AnimeTracker-Modern.ps1
```

Or directly:

```powershell
.\.venv\Scripts\python.exe -m anime_tracker.gui_qt.application
```

The window is labeled `Development / Migration Test Profile`. It copies the ignored migration-test prototype into `modern_profile_test`, never opens the live legacy database for writing, does not scan production roots automatically, and cannot send production Discord messages. Reset only that disposable profile with:

```powershell
.\Run-AnimeTracker-Modern.ps1 --reset-profile
```

## Scheduled Daily Check

```powershell
.\Create-ScheduledTask.ps1
```

The scheduled task runs once daily, silently refreshes AniList status, scans Jellyfin folders, and sends notifications only when meaningful changes occur.

## Notifications

Open `Settings` to configure notifications.

- Discord notifications are the primary notification method.
- The Discord webhook URL is stored in `data/notification_config.json`.
- That local config file is excluded by `.gitignore`.
- After the webhook is saved, the app only shows `Saved (hidden)` and does not display the full URL again.
- Windows toast notifications can be enabled as an optional secondary method.

Use `Send Test Notification` to verify the Discord webhook.

Discord notifications are sent once per event for:

- Upcoming to Currently Airing
- Currently Airing to Finished
- tracked title found on Jellyfin
- release-date changes
- repeated AniList API failures requiring attention

Each Discord message uses an embed with titles, previous/new status, episode count, Jellyfin found state, AniList link, cover image when available, and timestamp.

## Jellyfin Paths

Default paths:

- `I:\Jellyfin_Media\TV-SHOWs`
- `I:\Jellyfin_Media\Movies`

You can edit paths in the app with `Settings`.

## Usage

- `Add Anime`: type a title, paste an AniList URL, or paste an AniList ID.
- `Check All`: refresh tracked entries from AniList.
- `Scan Jellyfin`: read-only scan of configured Jellyfin roots.
- `Mark Added`: manually mark an entry as on server.
- `Edit`: edit notes, manual movie availability, server path, or status.
- `Remove from Tracker`: removes only the local tracker record after confirmation.
- `Export CSV`: export tracker rows.
- `Send Test Notification`: send a Discord test embed using the saved webhook.

## Movie Behavior

Anime movies are not considered ready just because AniList has a theatrical start date. Movie entries stay in `Movie Theatrical Only` until you manually confirm digital/Blu-ray availability, then they move to `Movie Digitally Available`.

## Sample Data

Run:

```powershell
.\.venv\Scripts\python.exe -m anime_tracker.app --sample-data
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

If `pytest` is unavailable:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## Files

- `src/anime_tracker/app.py`: GUI and command-line entry point.
- `src/anime_tracker/anilist.py`: AniList GraphQL client.
- `src/anime_tracker/database.py`: SQLite schema and persistence.
- `src/anime_tracker/status.py`: tracker status transition rules.
- `src/anime_tracker/domain/`: persistence-neutral modern domain models and deterministic rules (not yet a production cutover).
- `src/anime_tracker/services/anilist/`: typed modern AniList client, cache, batches, schedules, and franchise graph (not yet wired into production).
- `src/anime_tracker/services/server_inventory/`: transient typed filesystem snapshots, conservative media parsing, diagnostics, cancellation, and incremental reuse (not yet wired into production).
- `src/anime_tracker/services/matching/`: deterministic candidate ranking, typed season/movie targets, durable decisions, mapping history, coverage, and review workflows (not yet wired into production).
- `src/anime_tracker/notifications_v2/`: transactional outbox, deduplication, private/shared templates, retry policy, privacy filtering, baselines, summaries, and credential references (not yet wired into production).
- `src/anime_tracker/gui_qt/`: separate PySide6 development GUI, repositories, background workers, pages, dialogs, theme, and cover cache.
- `src/anime_tracker/scanner.py`: read-only Jellyfin matching.
- `src/anime_tracker/config.py`: local notification config storage.
- `src/anime_tracker/notifications.py`: Discord embeds and optional Windows toast notifications.
- `tests/`: automated tests.
