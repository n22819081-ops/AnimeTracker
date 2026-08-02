# AniList Service Design

## Scope

Milestone 3 adds `anime_tracker.services.anilist` beside the unchanged legacy `anilist.py`. It is not wired into the Tkinter GUI, scheduled command, Discord, Jellyfin scanning, or production database. All public provider operations return typed models or structured results; raw GraphQL dictionaries do not enter the domain layer.

## Interface

- `search_media`: AniList ID/URL, MAL ID, or paginated title search with optional year, format, and season filters.
- `get_media` and `refresh_media`: fresh-cache use, forced refresh, structured errors, and stale fallback.
- `get_media_page`: typed multi-ID page retrieval where a page query is practical.
- `refresh_batch`: sequential conservative requests, deduplication, archived exclusion, cancellation, and persistent per-item accounting.
- `get_relations`, `get_franchise_graph`, and `get_franchise_groups`: provider-confirmed edges and conservative grouping suggestions.
- `get_airing_schedule`, `get_recent_airings`, and `get_upcoming_airings`: timezone-aware typed schedules.
- `get_cache_status` and `invalidate_cache`: explicit cache state and per-record invalidation.

No operation directly updates a GUI widget or sends a notification.

## HTTP Boundary

The client permits only `https://graphql.anilist.co`. Requests contain a version-controlled query and allowlisted public variables with `(5 second connect, 20 second read)` timeouts. Unsupported variables and path/webhook-shaped string values are rejected before HTTP. It sends no local paths, Jellyfin data, usernames, computer data, webhooks, API keys, analytics, or telemetry. Public tracker operations require no AniList OAuth.

Errors are reduced to safe typed values: `RATE_LIMITED`, `TIMEOUT`, `CONNECTION_ERROR`, `GRAPHQL_ERROR`, `MALFORMED_RESPONSE`, `NOT_FOUND`, `INVALID_INPUT`, `CANCELED`, `OFFLINE_CACHE_USED`, `PARTIAL_BATCH_FAILURE`, and `CACHE_CORRUPT`. Logs contain the error type and attempt number, not variables, headers, provider bodies, or raw exception text.

## Typed Data

`AniListMedia` carries provider/MAL IDs, all title variants, format/status/season, partial dates, episode and duration fields, origin/source/genres/score/popularity, image URLs, page/description/adult flag, provider update time, next airing episode, schedule summary, relations, and digital availability. AniList movie digital availability remains `UNKNOWN`; AniList status or a theatrical date does not establish digital availability.

`AniListRelation` preserves source/target IDs, relation type, target format/status/title, direction, provider, and retrieval time. `AniListAiringEpisode` uses UTC-aware datetimes. `AniListRefreshResult` and `AniListRefreshBatch` expose cache/network behavior and partial failure without leaking provider JSON.

## Cancellation And Offline Use

Cancellation stops new requests, permits an in-flight HTTP request to finish or timeout, interrupts backoff, preserves completed cache writes, and marks unprocessed batch items canceled rather than failed. Cached media, relations, and schedules remain available offline with fresh/stale state. A failed refresh never blanks a valid cache record and does not itself create a provider status transition. A batch that serves usable stale data after network failures is `PARTIAL_FAILURE`, not full success.

## Fixtures And Live Check

The normal suite uses sanitized recorded-shape fixtures and injected fake sessions. `run_optional_live_check()` is disabled unless `ANIME_TRACKER_ANILIST_LIVE_CHECK=1`; when enabled it requests at most three public IDs and uses only a temporary test cache. It never writes the live tracker database.
