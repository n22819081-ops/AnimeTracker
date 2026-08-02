# Milestone 9 Verification

Version/build: `1.0.0` / `1.0.0-rc1`; schema 6. PyInstaller 6.21.0 produced a windowed 224-file onedir build with version/icon resources and Qt platform, image, style, network, TLS, SQLite, OpenSSL, requests, DPAPI, and notification dependencies. Inno Setup 6.7.3 compiled the per-user installer. The portable ZIP contains 224 valid members.

`pytest -q`: **659 passed, 47 subtests passed, 0 failed in 40.19s**. Disposable source-runtime validation passed for clean schema, configurable read-only Jellyfin roots, diagnostics, all 12 pages, scheduled SUCCESS/partial/offline/lock states, backup/restore, explicit adoption/source retention, and the production-profile copy: 69/69 resolved titles, 69/69 cover URLs, 421 archived records, 1,312 baselines, eight named reviews, one mapping, 11 rejections, and 27 candidates. Notification delivery stayed Stage 1.

Microsoft Defender on 2026-08-02 found no threats in distribution, installer, or ZIP (engine `1.1.26060.3008`, product `4.18.26060.3008`, signatures `1.455.472.0`). Privacy audit passed. Security audit passed statically and at source runtime.

**Release-candidate blocker:** this controlled Codex environment denied process creation for generated unsigned EXEs, including the app and installer, before their code ran. Fresh install, same-version reinstall, uninstall, installed/portable launch, packaged scheduled-check, and packaged path-relocation execution remain unverified. No clean VM was available. For this reason Milestone 9 is prepared but not declared complete.

Jellyfin media, the legacy task/database, production Discord activation, and the separate Storage Checker were untouched. Milestone 10 was not started.
