# Production Metadata Binding

## Read Path

```text
production_profile/data/anime_tracker_modern.db
  -> anilist_media_cache (normalized provider payload)
  -> anilist_media + media_titles (canonical persisted metadata)
  -> tracked_media + tracking_state + media_server_mappings
  -> ModernRepository
  -> AnimeRow display record
  -> Qt models, pages, and dialogs
```

Widgets do not open SQLite connections or perform joins. `ModernRepository` stores only the database path and opens short-lived connections per operation.

## Title Contract

`resolve_display_title(TitleMetadata)` is the only display-title policy:

1. English
2. Romaji
3. Native
4. Legacy stored title
5. `AniList <ID>` emergency fallback

The repository title CTE compares `lower(title_type)` to the schema's lowercase values. Canonical columns are preferred; valid cache JSON supplies secondary metadata when a canonical field is absent. Relation target titles use the same contract.

## Query Shape

The active tracked-media read uses two SQL statements regardless of row count: one joined display-record query and one relation-target query. Review rows use one joined review query and one candidate query. Secondary history, rejection, review, and suppression evidence loads only when a detail dialog opens.

## Covers

`CoverDelegate` asks `CoverImageCache` for a fixed 52 x 73 thumbnail. The cache reads disk first, retains valid cached images across network failures, and uses Qt's asynchronous network manager for missing images. Empty or pending covers paint a graphical placeholder without text. Details use the same cache at 150 x 210.

## Settings Boundary

The notification checkboxes control event generation preferences saved in sanitized profile settings:

- `notifications_private_enabled`
- `notifications_shared_enabled`
- `notifications_windows_enabled`

They do not enable credentials or delivery. Production delivery remains governed separately by bootstrap activation stage and credential-reference state. Stage 1 displays `Preview Only`; changing a checkbox performs no network operation.
