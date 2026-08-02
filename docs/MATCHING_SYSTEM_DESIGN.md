# Matching System Design

## Boundaries

Milestone 5 is a persistence-backed service layer, not a production cutover. It accepts typed AniList metadata, relations, and an in-memory read-only inventory snapshot. It emits suggestions, mappings, coverage evaluations, diagnostics, and review cases. It has no GUI, HTTP, notification, scheduling, subprocess, or media-write dependency.

Provider identity (AniList ID), franchise identity, inventory item identity, season scope, and episode/movie coverage remain separate. A path is evidence, not identity by itself.

## Targets And Sessions

Targets are `SERIES_FOLDER`, `SERIES_SEASON`, `SERIES_SPECIALS`, `MOVIE_ITEM`, `SEPARATE_SERIES`, `UNKNOWN_TARGET`, or `NO_SERVER_MAPPING`. Each carries library kind, root label, relative and normalized path, stable inventory item ID, optional season, content kind, snapshot fingerprint, display name, and path state.

A matching session records the inventory fingerprint, AniList metadata version, timestamps, candidate and warning counts, partial state, and cancellation state. Candidate IDs are hashes of session ID plus target identity, so item enumeration order cannot alter them. Confirmation transactionally revalidates both fingerprints; stale candidates raise `StaleCandidateError`.

## Generation And Confirmation

Candidate generation compares English, romaji, native, and synonym titles plus year, format, explicit season, episode range, Season 00 evidence, movie evidence, relation-backed parent mappings, confirmed mappings, and rejections. A normal no-match returns zero candidates and no review.

Scores only rank suggestions. Milestone 5 never auto-confirms. A unique strong candidate may be preselected only with explicit scope, matching media kind, no close competitor, no active mapping, no suppression, no rejection, no mixed-folder warning, and no absolute-number ambiguity.

Manual confirmation persists evidence and supersedes any prior active mapping. It never deletes prior mappings or history. A confirmed or broken mapping prevents a scan from preselecting a replacement.

## Coverage And Diagnostics

Coverage is calculated from the exact mapped season, approved Season 00 group, separate series, or movie item. Unrelated seasons in a shared folder are excluded. Diagnostics expose normalized provider inputs, score components, relative paths, inventory and relation evidence, mapping-history count, rejection effects, blockers, stale state, and next action. They do not contain webhook values.

Absolute numbers are retained as evidence but are not converted to season episodes. Ambiguous absolute numbering creates `ABSOLUTE_NUMBERING_UNRESOLVED` and requires a future explicit episode mapping.
