# Airing Event Rules

Airing timestamps are stored and compared as timezone-aware UTC datetimes. Local-time conversion belongs to a future presentation layer.

Snapshot comparison may emit typed candidates:

- `NEW_EPISODE_AIRED`: an episode moved from future/unknown to aired.
- `NEXT_EPISODE_SCHEDULED`: a new future episode appeared.
- `AIRING_TIME_CHANGED`: a scheduled time moved earlier or otherwise changed.
- `EPISODE_DELAYED`: a scheduled time moved later.
- `AIRING_SCHEDULE_REMOVED`: a previously future episode disappeared.
- `SEASON_STARTED_AIRING`: provider status changed from not-yet-released to releasing.
- `SERIES_FINISHED_AIRING`: provider status changed to finished, accompanied by final-episode/no-future-schedule evidence fields.

Equal snapshots emit no events. Missing schedule data alone emits no event. AniList `FINISHED` remains authoritative provider state; conflicting end-date/final-episode/schedule evidence creates warnings. None of these events claims Jellyfin coverage or sends Discord notifications.
