# Milestone 8 Acceptance Fixes

## Scope

This correction repairs production GUI metadata binding, covers, notification controls, and page filters. It does not approve cutover, package Milestone 9, send notifications, change Task Scheduler, access the Storage Checker, or write Jellyfin media.

## Root Causes

1. `media_titles.title_type` is constrained to lowercase values, but `ModernRepository` queried `ENGLISH`, `ROMAJI`, and `NATIVE`. Every subquery returned null even though all 69 production records had titles.
2. The table model intentionally converted every nonempty cover URL to the text `Cover`; the details dialog always constructed a text placeholder and never used `CoverImageCache`.
3. Notification checkboxes were created as unnamed local widgets and explicitly disabled. They also read `notifications_*` keys while production bootstrap uses separate delivery keys. No explanation distinguished event generation from Stage 1 delivery.
4. Every status page inherited one global status filter list, including options that could not affect that page.

## Corrections

- Added `TitleMetadata` and `resolve_display_title()` with the order English, Romaji, native, legacy title, emergency AniList ID.
- Replaced correlated title subqueries with a lowercase, aggregate title CTE and one bulk relation query. Cache JSON remains a secondary metadata source.
- Added the typed display fields needed by tables, details, review, franchise, coverage, notifications, and history.
- Resolved relation targets with the same title resolver while preserving relation type and direction.
- Added graphical cover delegates, fixed thumbnail geometry, disk-first cache reads, nonblocking Qt network loading, and graphical placeholders.
- Enriched review rows with titles, identity context, mappings, candidate evidence, and meaningful explanations.
- Added coverage-specific columns and explicit `No confirmed server mapping` wording.
- Made private Discord, shared Discord, and Windows event-generation controls independently visible and persistent. Delivery remains separately blocked at Stage 1 Preview Only.
- Added page-specific status filters and retained global search on data pages.

## Acceptance Result

- Production rows with resolved titles: 69/69
- Production rows with cover URLs: 69/69
- Named review cases: 8/8
- Named franchise entries: 69/69
- Named coverage entries: 69/69
- Sample detail dialogs with resolved metadata: 5/5
- Notification controls visibly interactive: 3/3
- Notification delivery stage: Stage 1 Preview Only
- Full suite: 643 passed and 47 subtests passed

There are no genuine unknown active titles. Optional provider fields remain honestly absent where AniList does not provide them: season/year is present for 61 records and episode count for 45.
