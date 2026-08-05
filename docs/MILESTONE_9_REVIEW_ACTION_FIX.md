# Milestone 9 Review Action and Live Scan Acceptance Fix

## Root causes

The matching review dialog created anonymous action buttons but connected only the dialog button box's accept and reject signals. `Mark Not on Server` therefore had no controller, service, repository, transaction, error, or refresh path. Migrated review cases without `review_case_candidates` rendered an empty table because candidate-backed fields were always shown.

The production inventory operation persisted complete `inventory_snapshots` but stopped there. It did not regenerate candidates, revalidate mappings, calculate coverage, update tracking state, or return a useful completion summary. The production toolbar also retained test-profile wording. Candidate preparation initially recomputed the complete 12,335-file snapshot hash for every possible target; the fixed pipeline reuses the matching session's existing snapshot identity and persists all prepared sessions/candidates/reviews in one thread-owned transaction.

## Review action

Candidate-free review presentation now shows the anime identity, review reason, and `No Jellyfin candidate was found for this title.` Candidate-only fields are hidden. Confirm and reject are absent when inapplicable. Mark Not on Server and Suppress Automatic Matching remain available; Choose Folder Manually is visibly disabled with an explanation because that packaged workflow is not implemented.

`Mark Not on Server` requires only `review_id`, `profile_id`, and `anilist_id`. One atomic transaction validates the active title and review, creates an idempotent `NOT_ON_SERVER` override, resolves only the selected review, recalculates `tracking_state`, and appends one `MANUALLY_MARKED_NOT_ON_SERVER` history event. Existing mappings are preserved. Repeated clicks do not duplicate overrides or history. Exceptions remain visible and are logged safely; the dialog stays open.

Affected tables:

- `mapping_overrides`: durable manual decision
- `review_cases`: selected case resolution only
- `tracking_state`: server presence, workflow group, review state, and last-check time
- `status_history`: one manual-decision history event

No notification, scheduling, inventory, mapping, rejection, credential, or media table is changed by this action.

## Review lifecycle

A complete scan relinks migrated candidate-driven reviews to current candidate/session identities. Candidate-driven reviews that cannot be reproduced by a complete scan are superseded with `NO_CURRENT_CANDIDATE`; no replacement review is created because no match is a normal Not on Server state. Confirmed-path, legacy-scope, identity-change, season, and other mapping-backed reviews remain open. An active manual Not on Server or No Valid Candidate decision prevents future candidates from opening a new candidate-driven review or becoming preselected.

## Live scan pipeline

The production action is labeled `Scan Jellyfin Libraries - Read Only` and confirms the exact configured roots before starting. A complete scan now:

1. Commits the complete inventory snapshot while retaining all prior snapshots.
2. Generates candidates for 69 active cached AniList identities.
3. Applies rejections and manual suppression decisions.
4. Persists sessions, candidates, and genuine reviews without auto-confirming mappings.
5. Revalidates confirmed mappings and stores coverage snapshots.
6. Reconciles stale candidate-only reviews and tracking state.
7. Refreshes all GUI pages and displays an operation summary.

Partial or failed scans retain the previous complete snapshot and skip candidate regeneration from incomplete evidence.

## Acceptance results

The final run used a disposable byte copy of the production profile and read the configured Jellyfin roots without modifying them:

- 587 library items
- 12,335 files
- 10,843 media files
- 69 titles processed
- 13 candidate suggestions across 12 titles
- 1 legacy mapping revalidated
- 0 mappings auto-confirmed
- 0 integration failures
- 6.67 seconds end to end
- 3 candidate-backed review dialogs after reconciliation
- 2 obsolete no-current-candidate ambiguity reviews superseded
- 6 genuine review cases retained, including legacy mapping scope/identity cases

Offline AniList-cache acceptance checked all 69 titles: 69 succeeded, 0 failed, 69 cache hits, 0 network requests, and 0 metadata changes.

The rebuilt packaged executable was assembled successfully. Direct packaged smoke execution remains blocked/hanging under the controlled Codex process policy and was terminated; no disposable packaged process was left running. Real installed-GUI acceptance must be repeated by the user with the superseding installer.

## Safety

The production profile database, settings, and bootstrap were unchanged during implementation and acceptance. All live inventory access was read-only and all acceptance writes went to disposable profile copies. Jellyfin media, Discord delivery, Task Scheduler, the legacy database, and the Jellyfin Storage Checker were untouched.

## Refresh and presentation acceptance repair

The packaged Qt worker previously wrapped `threading.Event` in a private `_EventToken` exposing only `is_canceled`. AniList retry/rate-limit code correctly called `wait(timeout)`, so a cache miss or network retry raised `AttributeError`. The shared `Cancellation` protocol now defines `is_cancelled()`, `cancel()`, and interruptible `wait(timeout)`. `CancellationToken` implements it and is passed directly by GUI refresh, Jellyfin scan, and scheduled-check workers; legacy Event-style aliases remain only at the worker callable boundary. Retry and rate-limit waits remain interruptible, completed partial results remain persisted, and worker exceptions still reach the GUI.

The installed final package was exercised against a disposable copy of the 69-title production profile. Refresh All Active completed with 69 checked, 69 succeeded, zero failed, 24 cache hits, 47 network requests, and zero metadata changes. The completion dialog appeared normally and no notification baseline or delivery path was invoked.

Candidate evidence is formatted once into readable lines. Raw JSON is hidden behind an explicit technical-details control, false `absolute_numbering` evidence is omitted, and semantically overlapping warnings are deduplicated. The Dangers in My Heart Season 2 displayed `The Dangers in My Heart (2023) - Season 02`, `STRONG`, and `132` Match points, plus parent-folder, season, episode, and conflict details. No mapping was confirmed.

The review table now has stable interactive widths, elided cells, and a fixed details panel. A 13-candidate automated resize loop performed no repository query and no formatter/model rebuild, completing below the 1.5-second smoke ceiling.
