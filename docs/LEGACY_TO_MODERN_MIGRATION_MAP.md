# Legacy-To-Modern Migration Map

## Migration Rules

- Source is opened with SQLite URI `mode=ro&immutable=1`; destination is a new database.
- `legacy_payload_json` preserves every field of each active `anime` row. `archived_legacy_records.payload_json` preserves every uncertain or ownerless row.
- Stable ownership requires an exact valid AniList ID. Titles and paths are never used to infer an orphan owner.
- A missing owner, malformed identity, or duplicate identity is `Manual review required`.
- Blank legacy values remain blank or null. The migration does not invent dates, episode counts, seasons, relations, or coverage.
- Path spelling is preserved in `original_path`; a case/slash-normalized comparison value is stored separately.
- Every source table is validated through `migration_audit`: source = active + archived + explicitly excluded technical rows.
- Conflicts never overwrite an earlier record. The conflicting row is archived whole.

## Milestone 2 Compatibility Adapter

`anime_tracker.domain.legacy_adapter` converts row-like values into typed domain inputs without querying SQLite. Legacy `On Server` preserves its manual confirmation through an explicit legacy override while coverage remains `UNKNOWN_COVERAGE`. Legacy `Not Found` becomes `NOT_FOUND` with no review. Legacy `Needs Review` becomes `LEGACY_DATA_REVIEW` when the precise cause is unavailable, and `Missing - Needs Review` becomes `PATH_MISSING` plus `MISSING_CONFIRMED_PATH`. The adapter never invents episode inventory or relation edges.

## `anime`

| Source column | Meaning | Destination | Transformation / null behavior | Conflict / orphan behavior | Validation |
|---|---|---|---|---|---|
| `id` | Legacy tracker PK | `tracked_media.legacy_anime_id` | Exact integer; also retained in payload | Duplicate legacy PK cannot exist in source; destination uniqueness enforced | Compare sampled IDs |
| `english_title` | English display title | `media_titles(title_type='english')` | Insert when nonblank; normalize separately | Duplicate identical title ignored only within same media/type | Title counts and payload |
| `romaji_title` | Romaji title | `media_titles(title_type='romaji')` | Insert when nonblank | Same as English | Title counts and payload |
| `native_title` | Native-script title | `media_titles(title_type='native')` | Insert when nonblank | Same as English | Title counts and payload |
| `alternate_titles` | JSON synonym list | `media_titles(title_type='synonym')` | Parse valid JSON list; blank means none | Malformed JSON remains in payload and emits warning; no guessed synonyms | Payload plus warning |
| `anilist_id` | Stable provider identity | `anilist_media.anilist_id`, `tracked_media.anilist_id` | Must be positive integer | Malformed or duplicate ID archives whole row; Manual review required | Unique constraint and audit |
| `format` | AniList format | `anilist_media.media_format` | Exact legacy value; blank remains blank | None | Sample comparison |
| `season` | AniList release season | `anilist_media.season_name` | Exact value | None | Sample comparison |
| `year` | AniList season year | `anilist_media.season_year` | Integer or null | None | Sample comparison |
| `total_episodes` | Provider expected episodes | `anilist_media.episode_count` | Integer or null; does not imply server coverage | None | Sample comparison |
| `airing_status` | AniList status | `anilist_media.anilist_status` | Exact value; remains separate from workflow | Unknown values retained | Distribution comparison |
| `start_date` | Provider start date | `anilist_media.start_date` | Exact partial/full date string | Blank remains blank | Sample comparison |
| `expected_end_date` | Provider end date | `anilist_media.end_date` | Exact partial/full date string | Blank remains blank | Sample comparison |
| `cover_image_url` | Provider cover URL | `anilist_media.cover_image_url` | Exact non-secret URL | Blank remains blank | Payload comparison |
| `anilist_url` | Provider page URL | `anilist_media.page_url` | Exact URL | Blank remains blank | AniList-ID sample |
| `tracker_status` | Legacy workflow group | `tracking_state.tracker_status` | Exact value; no status collapsing | Unknown values retained for review | Distribution comparison |
| `server_status` | Legacy server state | `tracking_state.legacy_server_status`, `server_presence` | Exact value retained; conservative presence derives to `NOT_ON_SERVER`, `NEEDS_REVIEW`, or `UNKNOWN_COVERAGE` | Never becomes coverage-complete solely from legacy `On Server` | Rule tests |
| `detected_server_path` | Legacy observed path | `tracked_media.legacy_payload_json` | Preserved only; not promoted without a `server_matches` row | Unconfirmed path ownership is not inferred | Payload presence |
| `date_added` | Tracking creation date | `tracked_media.added_at` | Exact value; missing uses migration timestamp with warning potential | None | Sample comparison |
| `last_checked` | Last provider check | `tracking_state.last_checked`, `anilist_media.source_updated_at` | Exact value | Blank remains blank | Sample comparison |
| `previous_status` | Legacy prior workflow value | `tracked_media.legacy_payload_json` | Preserved, not converted into a fabricated history event | Manual review if needed | Payload presence |
| `notification_state` | Legacy notification hint | `tracked_media.legacy_payload_json` | Preserved; delivery truth comes from `notification_events` only | Never marks a modern delivery | Payload presence |
| `manual_notes` | User notes | `tracked_media.manual_notes` | Exact text | None | Sample comparison |
| `movie_availability` | Manual movie state | `tracking_state.movie_availability` | Exact value; default `unknown` when absent | Unknown values retained | Distribution comparison |
| `api_failure_count` | Consecutive API failures | `tracked_media.legacy_payload_json` | Preserved for audit; not treated as current operational state | None | Payload presence |
| `relation_label` | Simplified legacy relation label | `anilist_media.relation_label_legacy` | Exact value; not promoted to a relation edge | Explicit AniList relation refresh required later | Sample comparison |
| `review_reason` | Legacy review explanation | `tracking_state.review_reason`, `review_cases.reason` | Opens a legacy review case when nonblank or tracker status is Needs Review | Blank Needs Review gets generic legacy reason | Review count |

## `server_matches`

| Source column | Meaning | Destination | Transformation / null behavior | Conflict / orphan behavior | Validation |
|---|---|---|---|---|---|
| `anilist_id` | Mapping owner | `media_server_mappings.legacy_anilist_id`, FK through tracked media | Exact ID lookup | Missing active owner archives whole row; Manual review required | Owner/orphan counts |
| `path` | Confirmed folder | `server_library_items.original_path`, `normalized_path`; `jellyfin_folder_mappings` | Preserve original and normalize comparison value | Same normalized path reuses one library item, allowing many AniList mappings | Shared-path test |
| `season_label` | Legacy scope hint | `media_server_mappings.season_number/target_kind` | Parse only explicit `Season N`; otherwise `UNSPECIFIED` | Unspecified scope opens review case; no chronology inference | Mapping-scope checks |
| `confirmation_type` | Manual/automatic provenance | `media_server_mappings.confirmation_type` | Exact value; missing becomes `legacy` | None | Distribution comparison |
| `confirmed_at` | Confirmation date | `media_server_mappings.confirmed_at` | Exact value; blank uses migration timestamp | None | Sample comparison |

## `rejected_matches`

| Source column | Meaning | Destination | Transformation / null behavior | Conflict / orphan behavior | Validation |
|---|---|---|---|---|---|
| `anilist_id` | Decision owner | `rejected_match_decisions.legacy_anilist_id`, tracked FK | Exact lookup | Missing owner archives whole row | Owner/orphan counts |
| `path` | Legacy comparison path | `normalized_path` fallback | Normalize only when dedicated field blank | Path-specific only; never implies title-wide block | Rejection tests |
| `normalized_path` | Canonical comparison value | `rejected_match_decisions.normalized_path` | Preserve nonblank value | Duplicate decision constrained | Count comparison |
| `original_path` | Human path spelling | `rejected_match_decisions.original_path` | Fallback to `path` | None | Payload/path fingerprint |
| `rejected_at` | Decision date | `rejected_match_decisions.decided_at` | Exact or migration timestamp | None | Sample comparison |

`block_auto_match` is initialized to `0`. A legacy rejected path cannot be interpreted as “never auto-match this title.”

## `match_candidates`

| Source column | Meaning | Destination | Transformation / null behavior | Conflict / orphan behavior | Validation |
|---|---|---|---|---|---|
| `anilist_id` | Candidate owner | `match_candidates.tracked_media_id` | Exact owner lookup | Missing owner archives whole row | Owner/orphan counts |
| `path` | Candidate folder | `original_path`, `normalized_path` | Preserve and normalize | Duplicate owner/path constrained | Count comparison |
| `confidence` | Legacy confidence label | `confidence_label` | Exact value | Unknown retained | Sample comparison |
| `score` | Legacy numeric score | `score` | Integer, default 0 only when absent | None | Sample comparison |
| `reasons` | JSON evidence list | `reasons_json` | Preserve exact JSON text | Malformed text retained for later review | Payload comparison |
| `year` | Folder year | `folder_year` | Integer or null | None | Sample comparison |
| `media_kind` | TV/movie candidate kind | `media_kind` | Exact value, absent becomes `UNKNOWN` | None | Distribution comparison |
| `scanned_at` | Candidate scan date | `scanned_at` | Exact or migration timestamp | None | Sample comparison |

## `status_history`

| Source column | Meaning | Destination | Transformation / null behavior | Conflict / orphan behavior | Validation |
|---|---|---|---|---|---|
| `id` | Legacy event PK | `status_history.legacy_history_id` | Exact | Duplicate constrained | Count/sample |
| `anilist_id` | Event owner | `tracked_media_id` lookup | Exact owner lookup | Null or missing owner archives whole row | Owner/orphan counts |
| `event` | Event description | `event_type` | Exact legacy text | None | Event distribution |
| `previous_status` | Previous workflow | `previous_tracker_status` | Exact | Blank remains blank | Sample comparison |
| `new_status` | New workflow | `new_tracker_status` | Exact | Blank remains blank | Sample comparison |
| `server_path` | Historical path snapshot | `server_path_snapshot` | Exact, not treated as current mapping | None | Payload comparison |
| `created_at` | Event date | `created_at` | Exact or migration timestamp | None | Sample comparison |

## `notification_events`

| Source column | Meaning | Destination | Transformation / null behavior | Conflict / orphan behavior | Validation |
|---|---|---|---|---|---|
| `event_key` | Legacy dedupe key | `notification_outbox.event_key` | Exact unique key | Duplicate constrained | Count comparison |
| `event_type` | Event type | `notification_outbox.event_type` | Exact | None | Distribution comparison |
| `anilist_id` | Optional owner | `notification_outbox.payload_json` | Preserve ID only, no secret content | Missing non-null owner archives row | Owner/orphan counts |
| `sent_at` | Legacy sent time | `outbox.delivered_at`, `notification_deliveries.attempted_at` | Exact or migration timestamp | Legacy row is treated as delivered evidence | Delivery count |

## `jellyfin_announcement_snapshot`

| Source column | Meaning | Destination | Transformation / null behavior | Conflict / orphan behavior | Validation |
|---|---|---|---|---|---|
| `item_type` | Show/movie/season kind | `announcement_baselines.item_type` | Exact | Unknown retained | Count comparison |
| `normalized_path` | Snapshot identity | `normalized_path` | Exact | Duplicate constrained per shared channel | Unique/count |
| `parent_normalized_path` | Parent show identity | `parent_normalized_path` | Exact; blank remains blank | None | Sample comparison |
| `title` | Snapshot display title | `title` | Exact | None | Sample comparison |
| `year` | Folder year | `year` | Integer or null | None | Sample comparison |
| `season_number` | Season identity | `season_number` | Integer or null | No season inference | Sample comparison |
| `original_path` | Original path | `original_path` | Exact | None | Fingerprint comparison |
| `captured_at` | Baseline time | `captured_at` | Exact | None | Sample comparison |

## `manual_announcement_queue`

| Source column | Meaning | Destination | Transformation / null behavior | Conflict / orphan behavior | Validation |
|---|---|---|---|---|---|
| `id` | Legacy queue PK | `legacy_id` | Exact | Duplicate constrained | Count comparison |
| `media_type` | TV/movie kind | `media_type` | Exact | Unknown retained | Sample comparison |
| `title` | Display title | `title` | Exact | None | Sample comparison |
| `normalized_title` | Duplicate key | `normalized_title` | Exact | None | Sample comparison |
| `year` | Optional year | `year` | Integer or null | None | Sample comparison |
| `season_number` | TV season | `season_number` | Integer or null | No inference | Sample comparison |
| `episodes_json` | Episode list | `episodes_json` | Exact JSON text | Malformed text retained | Payload comparison |
| `created_at` | Queue creation | `created_at` | Exact | None | Sample comparison |
| `updated_at` | Queue update | `updated_at` | Exact | None | Sample comparison |

## `manual_announcement_titles`

| Source column | Meaning | Destination | Transformation / null behavior | Conflict / orphan behavior | Validation |
|---|---|---|---|---|---|
| `media_type` | Suggestion kind | `media_type` | Exact | Composite uniqueness retained | Count comparison |
| `normalized_title` | Suggestion identity | `normalized_title` | Exact | Composite uniqueness retained | Count comparison |
| `title` | Display suggestion | `title` | Exact | None | Sample comparison |
| `year` | Optional year | `year` | Integer or null | None | Sample comparison |
| `last_used_at` | Last use | `last_used_at` | Exact | None | Sample comparison |

## `settings`

| Source column | Meaning | Destination | Transformation / null behavior | Conflict / orphan behavior | Validation |
|---|---|---|---|---|---|
| `key` | Setting name | `application_settings.key` | Exact non-secret key | Secret-like key archives whole row; Manual review required | Key/count comparison |
| `value` | Setting value | `application_settings.value` | Exact non-secret value | Webhook/token/password/API-key-like settings are never imported into ordinary settings | Redaction test |

Real Discord secrets live in the separate JSON file and are not part of prototype migration. Future credential migration follows `SECRET_STORAGE_PLAN.md`.

## Deleted Anime And Orphan Rows

The legacy database has no removed/archived anime table. Child rows whose AniList ID has no active `anime` owner are preserved in `archived_legacy_records` with source table, source key, original AniList ID, complete JSON payload, timestamp, and `Manual review required`. Reassociation is prohibited unless future evidence proves origin.
