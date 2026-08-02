# Anime Tracker Implementation Plan

## Goals

Build a local Windows desktop application that tracks anime intended for a Jellyfin server, using AniList for anime metadata and SQLite for local state. The application must only read Jellyfin media folders and must never rename, move, modify, replace, or delete files in those folders.

## Architecture

- Python package under `src/anime_tracker`.
- SQLite database stored in `data/anime_tracker.db`.
- Tkinter desktop GUI for normal use.
- AniList GraphQL API client for metadata lookup and refresh.
- Read-only Jellyfin scanner that compares folder names against normalized titles, alternate titles, format, and year.
- Windows toast notifications via `winotify`, with a safe fallback to logging when unavailable.
- PowerShell scripts for install, launch, and Windows Task Scheduler setup.
- Automated unit tests for normalization, status transitions, and server matching.

## Data Model

The main `anime` table stores AniList identity fields, title variants, dates, episode counts, tracker/server status, detected path, notification state, notes, and audit timestamps. Settings are stored separately so Jellyfin roots can be configured without code changes.

## Core Workflow

1. User adds anime by title, AniList URL, or AniList ID.
2. Title searches with multiple matches show a selection dialog.
3. AniList metadata is stored locally.
4. Status refresh updates all tracked entries and sends notifications once per meaningful transition.
5. Jellyfin scan reads configured roots, compares candidates conservatively, and only marks confident matches as `On Server`.
6. Ambiguous matches move entries to `Needs Review` with notes describing possible paths.
7. Movies remain theatrical-only unless digital/Blu-ray availability is manually confirmed.

## Safety Rules

- Jellyfin paths are scanned with read-only directory traversal.
- No code path performs rename, move, delete, replace, or write operations inside configured Jellyfin roots.
- Tracker removal deletes only the local database entry after confirmation.
- Bulk operations create a timestamped SQLite backup before changing tracked rows.

## Smallest Working Version

The first working version includes:

- Tkinter table with search/filter and core buttons.
- Add by title, URL, or ID.
- AniList refresh and silent scheduled check.
- Read-only Jellyfin scan.
- CSV export.
- Manual edit/mark-added/remove workflows.
- PowerShell scripts and README.
- Unit tests.

