# Anime Tracker 1.0.0 Release Manifest

Build `1.0.0-rc1` dated 2026-08-15; schema 6; unsigned.

- Main EXE: `Anime Tracker.exe` (`C41CE307670EAA4980F4E6A2E0C19EDA042A7ED874DDD2DEA7A7CC2AE54D549C`)
- Installer: `Anime-Tracker-Setup-1.0.0.exe` (`A071855A386A3395C69ABFE9F806B6C5FF93E24A52AFD3C5E1D98BA9445EBCF6`)
- Portable ZIP: `Anime-Tracker-Portable-1.0.0.zip` (`C204E48353E65FA0A783AE1CB4F81BFE645A3BA1565653C6F7752B8554645475`)
- Distribution: 223 files
- Tests: 707 passed, 47 subtests passed, 0 failed in 45.52s; 18 packaged-release tests passed
- Installer/reinstall: PASS, final per-user package installed over current build
- Profile adoption: PASS on disposable production-profile copy; source retained
- Existing-profile detection: PASS: absolute project-local path, read-only integrity/FK/schema/count validation, both actions enabled
- Review action: PASS: candidate-free and explicit candidate actions persist; detail actions open; pages refresh
- Mapping confirmation: PASS on a disposable production copy for Dangers S2, Bakemonogatari S1, and Beautiful Bones S1
- Coverage inventory: PASS; all 587 latest-snapshot server folders are available in By server folder
- Runtime repairs: PASS installed; Fragtime is no longer duplicated in Movies, Beautiful Bones is one combined review, stale schedules are labeled, and single-result folder search selects itself
- Search/manual mapping: PASS; AniList's temporary API shutdown is reported truthfully with input preserved, and season-scoped manual folder selection is usable
- Shared chat: explicit title-only composer present; delivery remains confirmation-gated and no live message was sent during verification
- TLS: contaminated-PATH packaged smoke passed; Schannel/certificate plugins included and Qt OpenSSL plugin excluded
- Live scan integration: PASS on disposable production copy: 587 items, 12,335 files, 10,843 media files, 13 suggestions, 0 auto-confirmed
- Defender: no threats found in all scanned targets
- Privacy: PASS
- Packaged refresh: PASS, 69/69 succeeded with a visible completion summary
- Matching presentation: PASS, prose evidence, Match points, Season 02 scope, responsive resize
- Security: PASS (static, source runtime, and packaged GUI acceptance)

All previous Anime Tracker 1.0.0 RC hashes, including the August 5 installed build, are superseded by the hashes in this manifest and `SHA256SUMS.txt`. See the release notes for limitations.
