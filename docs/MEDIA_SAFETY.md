# Media Safety

Anime Tracker is a read-only tracker and scanner. It never modifies Jellyfin media.

It may read these configured roots:

- `I:\Jellyfin_Media\TV-SHOWs`
- `I:\Jellyfin_Media\Movies`

It must never rename, move, copy, replace, delete, edit, transcode, retimestamp, chmod, or otherwise modify files or folders in those libraries. It must never edit embedded metadata or invoke Sonarr/Radarr imports.

Anime Tracker must not invoke, import, modify, or control the separate `jellyfin storage checker` product or `Set-MKV-English-Defaults.ps1`.

All future scan sessions must be marked read-only. Database, log, export, cache, backup, and temporary writes must remain under application-controlled locations outside the Jellyfin roots. Output-path guards must reject the media roots and Storage Checker before creating any file.

Optional Jellyfin API support may be added later only for read-only queries. Filesystem scanning remains available without an API key.
