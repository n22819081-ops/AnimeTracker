# Milestone 9 Verification

Version/build: `1.0.0` / `1.0.0-rc1`; schema 6. PyInstaller 6.21.0 produced a windowed 224-file onedir build with version/icon resources and Qt platform, image, style, network, TLS, SQLite, OpenSSL, requests, DPAPI, and notification dependencies. Inno Setup 6.7.3 compiled the per-user installer. The portable ZIP contains 224 valid members.

`pytest`: **686 passed, 0 failed in 48.63s**. Disposable source-runtime validation passed for clean schema, configurable read-only Jellyfin roots, diagnostics, all 12 pages, scheduled SUCCESS/partial/offline/lock states, backup/restore, explicit adoption/source retention, candidate-free review actions, active-profile isolation, live snapshot persistence, candidate regeneration, review reconciliation, cancellation/backoff, cover-request cancellation, evidence presentation, resize performance, and the production-profile copy. Notification delivery stayed Stage 1.

## Existing-profile detection acceptance fix

The initial package built `PROJECT_PRODUCTION_PROFILE` from `Path("C:")`, producing drive-relative `C:AnimeTracker\production_profile`. Detection therefore depended on the current directory and failed from the installed application directory. The corrected runtime normalizes the system drive to `C:\` before joining path components, yielding absolute `C:\AnimeTracker\production_profile` without relying on source files, environment-specific working directories, bootstrap presence, or executable location.

Read-only validation now confirms `integrity_check=ok`, zero foreign-key violations, schema 6, 69 active titles, 421 archived/orphaned records, 1,312 baselines, eight reviews, one mapping, 11 rejections, 27 candidates, and redacted disabled DPAPI references. Tests confirm both first-run actions enable, invalid profiles show a reason, opening first run performs no writes, project-local mode loads 69 titles/all 12 pages, and adoption preview shows source/target/counts. Production database/bootstrap/settings hashes remained unchanged.

Microsoft Defender on 2026-08-04 found no threats in distribution, installer, or ZIP (engine `1.1.26070.7`, product `4.18.26060.3008`, signatures `1.457.1.0`). Privacy audit passed. Security audit passed statically, at source runtime, and through packaged GUI acceptance.

## Matching-review and live-scan acceptance fix

The review dialog's Mark Not on Server button was not connected to any application action. The corrected path validates the selected review and AniList identity, writes an idempotent manual decision, resolves only that review, recalculates tracker/server/review state, records history, refreshes all pages, and surfaces failures. It does not require a candidate ID, mapping, confidence, target, or path.

Production scanning previously ended after persisting `inventory_snapshots`. It now generates and persists candidates, reapplies rejections/manual decisions, revalidates confirmed mappings, stores coverage, reconciles migrated reviews, updates page models, and displays real summaries. The full disposable live-root run completed in 6.67 seconds with 587 items, 12,335 files, 10,843 media files, 13 suggestions across 12 titles, one mapping revalidated, zero auto-confirmations, and zero integration failures. Two obsolete ambiguity reviews with no current candidate were superseded; genuine legacy mapping reviews remained.

See `MILESTONE_9_REVIEW_ACTION_FIX.md` for affected tables, lifecycle details, and acceptance evidence.

## Refresh and matching presentation repair

The Refresh All Active crash was caused by the Qt worker's private token adapter lacking `wait(timeout)`. One shared cancellation protocol now covers AniList refresh, rate-limit backoff, retry delay, inventory scan, GUI workers, and scheduled checks. The installed final package completed a real refresh against a disposable 69-title profile: 69 succeeded, zero failed, 24 cache hits, 47 network requests, and zero metadata changes. A clear completion dialog was shown.

Matching evidence is prose in the normal table and structured JSON only in the optional technical view. The scorer remains unbounded and additive, so the UI says `Match points`, not Score or percent. Thresholds are documented in `MATCHING_SCORE_RULES.md`. Season-scoped targets include `Season 02`; the selected details show parent folder, scope, episodes, confidence, points, and conflicts before confirmation.

The review dialog prepares its model and evidence once. Interactive fixed initial widths, elision, and a separate details panel eliminate resize-triggered fitting, wrapping, formatting, or database access. The automated 13-candidate resize test rebuilt neither evidence nor model and stayed below its performance ceiling.

PyInstaller's upstream QtNetwork hook began blocking indefinitely in its build-time `QSslSocket.supportsSsl()` capability probe. A project-local hook retains standard QtNetwork dependency collection while skipping only that probe. The final 224-file distribution still contains the Schannel TLS backend and Python/OpenSSL runtime; release tests verify both.

The user confirmed that the packaged 1.0.0 first-run screen launches on the real Windows desktop. This acceptance pass also installed the final build over the existing per-user installation and exercised Refresh All Active and Review Server Match through the real packaged GUI using a disposable profile. No clean VM was available.

Jellyfin media, the legacy task/database, production Discord activation, and the separate Storage Checker were untouched. Milestone 10 was not started.
