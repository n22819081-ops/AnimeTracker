# Privacy

Anime Tracker stores data locally in the selected profile. Public release files contain no user database, webhook, DPAPI blob, log, backup, cache, inventory, media filename, personal path, profile, diagnostic, or screenshot. AniList public GraphQL queries require no API key.

Discord webhook values are DPAPI-protected outside SQLite. Diagnostics contain redacted credential state only. Jellyfin scanning reads configured paths; it does not upload media inventory to Anime Tracker services.
