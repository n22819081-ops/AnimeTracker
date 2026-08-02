# Milestone 9 Verification

Version/build: `1.0.0` / `1.0.0-rc1`; schema 6. PyInstaller 6.21.0 produced a windowed 224-file onedir build with version/icon resources and Qt platform, image, style, network, TLS, SQLite, OpenSSL, requests, DPAPI, and notification dependencies. Inno Setup 6.7.3 compiled the per-user installer. The portable ZIP contains 224 valid members.

`pytest -q`: **667 passed, 47 subtests passed, 0 failed in 38.85s**. Disposable source-runtime validation passed for clean schema, configurable read-only Jellyfin roots, diagnostics, all 12 pages, scheduled SUCCESS/partial/offline/lock states, backup/restore, explicit adoption/source retention, and the production-profile copy: 69/69 resolved titles, 69/69 cover URLs, 421 archived records, 1,312 baselines, eight named reviews, one mapping, 11 rejections, and 27 candidates. Notification delivery stayed Stage 1.

## Existing-profile detection acceptance fix

The initial package built `PROJECT_PRODUCTION_PROFILE` from `Path("C:")`, producing drive-relative `C:AnimeTracker\production_profile`. Detection therefore depended on the current directory and failed from the installed application directory. The corrected runtime normalizes the system drive to `C:\` before joining path components, yielding absolute `C:\AnimeTracker\production_profile` without relying on source files, environment-specific working directories, bootstrap presence, or executable location.

Read-only validation now confirms `integrity_check=ok`, zero foreign-key violations, schema 6, 69 active titles, 421 archived/orphaned records, 1,312 baselines, eight reviews, one mapping, 11 rejections, 27 candidates, and redacted disabled DPAPI references. Tests confirm both first-run actions enable, invalid profiles show a reason, opening first run performs no writes, project-local mode loads 69 titles/all 12 pages, and adoption preview shows source/target/counts. Production database/bootstrap/settings hashes remained unchanged.

Microsoft Defender on 2026-08-02 found no threats in distribution, installer, or ZIP (engine `1.1.26060.3008`, product `4.18.26060.3008`, signatures `1.455.472.0`). Privacy audit passed. Security audit passed statically and at source runtime.

The user confirmed that the packaged 1.0.0 first-run screen launches on the real Windows desktop. The controlled Codex environment still denies process creation for generated unsigned EXEs, so installer lifecycle and automated packaged relocation remain environment-blocked rather than claimed as independently certified. No clean VM was available.

Jellyfin media, the legacy task/database, production Discord activation, and the separate Storage Checker were untouched. Milestone 10 was not started.
