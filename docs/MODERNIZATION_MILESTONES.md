# Modernization Milestones

## Milestone 1: Foundation

- Verified immutable backup, hashes, manifest, and SQLite integrity checks.
- Valid local Git baseline and tag with protected data excluded.
- Legacy test, import, read-only database, and performance baselines.
- Read-only data-integrity inventory and orphan accounting.
- Normalized schema version 1 design.
- Conservative prototype migration and exact row reconciliation.
- Secret storage, backup/restore, and media-safety plans.

Status: implemented for validation. The legacy application remains active and unchanged.

## Milestone 2: Domain And Status Engine

Create typed core models and deterministic rules for AniList status, tracker workflow, server presence, episode coverage, review state, and archival behavior. Do not couple the engine to a GUI.

Status: implemented and regression-validated. The package is persistence-neutral and is not wired into the legacy application. Coverage, mapping, review, override, archive, transition, and legacy-adaptation rules are documented in `STATUS_ENGINE_RULES.md`.

## Milestone 3: AniList Service

Add cache TTLs, batched refreshes, rate-limit-aware retries, airing schedules, relation IDs, and a persistent franchise graph.

## Milestone 4: Read-Only Server Inventory

Build incremental filesystem snapshots and optional read-only Jellyfin API discovery for shows, seasons, episodes, movies, and specials.

## Milestone 5: Matching And Review

Implement many-to-one mappings, explicit season targets, Season 00 suggestions, durable rejections, title-wide auto-match blocks, and review-case workflows.

## Milestone 6: Notifications

Implement a transactional outbox, atomic claims, retries, meaningful private events, and separate shared announcements.

## Milestone 7: PySide6 GUI

Build the dark desktop interface, background workers, progress/cancellation, accessible review tools, and diagnostics.

## Milestone 8: Operations And Cutover

Integrate scheduling, verified backup/restore, credential migration, diagnostics, dual-read comparison, and production database cutover.

## Milestone 9: Packaging And Release

Package a Windows application, validate on a clean user profile, test upgrade/rollback, and publish a versioned release.

Milestone 3 and later are not part of the current implementation.
