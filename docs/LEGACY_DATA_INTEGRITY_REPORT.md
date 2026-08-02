# Legacy Data Integrity Report

This report was generated from the verified read-only modernization backup. It contains no webhook values and did not inspect Jellyfin media.

## Schema

- Explicit schema version: **No**
- Tables: **10**
- Explicit foreign keys: **0**
- Non-system indexes: **2**

## Row Counts

- `anime`: 69
- `jellyfin_announcement_snapshot`: 1312
- `manual_announcement_queue`: 0
- `manual_announcement_titles`: 3
- `match_candidates`: 114
- `notification_events`: 0
- `rejected_matches`: 19
- `server_matches`: 93
- `settings`: 16
- `status_history`: 374

## Tables And Columns

- **`anime`:** `id` (INTEGER), `english_title` (TEXT), `romaji_title` (TEXT), `native_title` (TEXT), `alternate_titles` (TEXT), `anilist_id` (INTEGER), `format` (TEXT), `season` (TEXT), `year` (INTEGER), `total_episodes` (INTEGER), `airing_status` (TEXT), `start_date` (TEXT), `expected_end_date` (TEXT), `cover_image_url` (TEXT), `anilist_url` (TEXT), `tracker_status` (TEXT), `server_status` (TEXT), `detected_server_path` (TEXT), `date_added` (TEXT), `last_checked` (TEXT), `previous_status` (TEXT), `notification_state` (TEXT), `manual_notes` (TEXT), `movie_availability` (TEXT), `api_failure_count` (INTEGER), `relation_label` (TEXT), `review_reason` (TEXT)
- **`jellyfin_announcement_snapshot`:** `item_type` (TEXT), `normalized_path` (TEXT), `parent_normalized_path` (TEXT), `title` (TEXT), `year` (INTEGER), `season_number` (INTEGER), `original_path` (TEXT), `captured_at` (TEXT)
- **`manual_announcement_queue`:** `id` (INTEGER), `media_type` (TEXT), `title` (TEXT), `normalized_title` (TEXT), `year` (INTEGER), `season_number` (INTEGER), `episodes_json` (TEXT), `created_at` (TEXT), `updated_at` (TEXT)
- **`manual_announcement_titles`:** `media_type` (TEXT), `normalized_title` (TEXT), `title` (TEXT), `year` (INTEGER), `last_used_at` (TEXT)
- **`match_candidates`:** `anilist_id` (INTEGER), `path` (TEXT), `confidence` (TEXT), `score` (INTEGER), `reasons` (TEXT), `year` (INTEGER), `media_kind` (TEXT), `scanned_at` (TEXT)
- **`notification_events`:** `event_key` (TEXT), `event_type` (TEXT), `anilist_id` (INTEGER), `sent_at` (TEXT)
- **`rejected_matches`:** `anilist_id` (INTEGER), `path` (TEXT), `rejected_at` (TEXT), `normalized_path` (TEXT), `original_path` (TEXT)
- **`server_matches`:** `anilist_id` (INTEGER), `path` (TEXT), `season_label` (TEXT), `confirmed_at` (TEXT), `confirmation_type` (TEXT)
- **`settings`:** `key` (TEXT), `value` (TEXT)
- **`status_history`:** `id` (INTEGER), `anilist_id` (INTEGER), `event` (TEXT), `previous_status` (TEXT), `new_status` (TEXT), `server_path` (TEXT), `created_at` (TEXT)

## Indexes

- `idx_manual_announcement_duplicate` on `manual_announcement_queue`
- `idx_rejected_matches_normalized` on `rejected_matches`

## Identity And Preservation

- Active tracked records: 69
- Duplicate AniList IDs: 0
- Null or malformed AniList IDs: 0
- Distinct removed identities inferred from orphan records: 97
- Legacy rows have no archived flag. Removed identities are not reassociated automatically.

## Server Mapping Summary

- Rows: 93
- AniList IDs with mappings: 93
- Maximum mappings for one AniList ID: 1
- Mappings-per-ID histogram: 1 mapping(s)=93 ID(s)
- Shared paths used by multiple AniList IDs: 1

## Orphaned Records

- `server_matches`: 92
- `rejected_matches`: 8
- `match_candidates`: 100
- `status_history`: 221
- `notification_events`: 0

Every orphan is retained by the prototype in `archived_legacy_records` with `Manual review required`.

## Status Distributions

- **anilist_status:** RELEASING=29, FINISHED=24, NOT_YET_RELEASED=16
- **tracker_status:** Currently Airing=29, Finished / Ready to Add=17, Upcoming=15, Needs Review=4, Movie Theatrical Only=3, On Server=1
- **server_status:** Not Found=64, Needs Review=4, On Server=1
- **format:** TV=52, ONA=5, TV_SHORT=4, OVA=4, MOVIE=3, SPECIAL=1
- **movie_availability:** unknown=69

## Consistency Checks

- `tracker_on_server_but_server_not_on_server`: 0
- `server_on_server_but_tracker_not_on_server`: 0
- `on_server_without_server_mapping`: 0
- `active_mapping_but_tracker_not_on_server`: 0
- `needs_review_without_review_server_status`: 0

## Stored Paths

Path existence was not checked. Only stored values, syntax, and database references were examined; path details are represented by fingerprints where needed.
- Empty stored paths: 0
- Syntactically invalid Windows paths: 0

## Settings

- `announcement_baseline_created`: `true`
- `movie_path`: `<configured-path:6657941c7392>`
- `schedule_day`: `Sunday`
- `schedule_discord_summary_changes_only`: `true`
- `schedule_enabled`: `true`
- `schedule_frequency`: `Weekly`
- `schedule_start_when_available`: `true`
- `schedule_time`: `10:00`
- `scheduled_last_check`: `2026-07-26T10:02:04`
- `scheduled_last_result`: `Success`
- `scheduled_moved_on_server`: `0`
- `scheduled_moved_ready`: `2`
- `scheduled_next_check`: `2026-08-02T10:00`
- `scheduled_titles_updated`: `42`
- `theme`: `Dark`
- `tv_path`: `<configured-path:4a999d222eab>`
