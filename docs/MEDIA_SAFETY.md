# Media Safety

Anime Tracker is a read-only tracker and scanner. It never modifies Jellyfin media.

It may read these configured roots:

- `I:\Jellyfin_Media\TV-SHOWs`
- `I:\Jellyfin_Media\Movies`
- `I:\Jellyfin_Media\Anime`

It must never rename, move, copy, replace, delete, edit, transcode, retimestamp, chmod, or otherwise modify files or folders in those libraries. It must never edit embedded metadata or invoke Sonarr/Radarr imports.

Anime Tracker must not invoke, import, modify, or control the separate `jellyfin storage checker` product or `Set-MKV-English-Defaults.ps1`.

All future scan sessions must be marked read-only. Database, log, export, cache, backup, and temporary writes must remain under application-controlled locations outside the Jellyfin roots. Output-path guards must reject the media roots and Storage Checker before creating any file.

The Milestone 2 domain package has no filesystem APIs, media-root strings, scanner imports, subprocess calls, or write operations. Its automated safety tests statically enforce the absence of GUI, network, SQLite, scanner, notification, and scheduler dependencies.

The Milestone 3 AniList service writes only explicitly configured schema-v3 cache databases. It contains no Jellyfin scanner, media-root, Discord, GUI, subprocess, or Task Scheduler dependency. Automated requests use injected fake sessions. AniList request variables contain only provider search/ID/filter/schedule values, never local media data.

Optional Jellyfin API support may be added later only for read-only queries. Filesystem scanning remains available without an API key.

The Milestone 4 filesystem inventory uses only directory enumeration and file metadata reads. Automated coverage uses temporary fixture roots. The inventory does not create a cache, database, marker, lock, sidecar, or log file under a media root.

The Milestone 5 matching layer consumes only already-built typed inventory snapshots. It does not enumerate live media roots itself and contains no media write, move, rename, delete, subprocess, external-tool, Discord, scheduler, or GUI operation. Its SQLite repository writes only to an explicitly supplied application database path; schema v4 refuses the live database and is exercised only on temporary or ignored migration-test copies. Matching diagnostics prefer relative paths and contain no notification credentials.
