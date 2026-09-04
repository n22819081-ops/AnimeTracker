# Anime Tracker 1.0.0 RC1

Build `1.0.0-rc1` packages the modern PySide6 application as a windowed onedir EXE, per-user Inno Setup installer, and portable ZIP. It adds clean-profile first run, explicit verified profile adoption, stable per-user data separation, packaged diagnostics/scheduled-check modes, About details, version resources, release audits, and documentation.

Existing production data is not embedded. Notifications remain Stage 1 Preview Only and scheduling remains opt-in. The legacy task remains unchanged. Known limitations include unsigned SmartScreen warnings, manual movie-digital confirmation, ambiguous absolute episode numbering, eight current production review cases, and deferred optional Jellyfin API integration.

The 2026-08-15 rebuild repairs user-reported navigation and review behavior: confirmed On Server movies no longer remain in Movies, multiple open reasons for the same anime are grouped into one review, and a unique manual folder search result selects itself and enables confirmation. Coverage wording distinguishes “not evaluated” from “none missing,” and expired AniList airing data is labeled as a cached schedule instead of being presented as current.

Notifications includes an explicit `New on Jellyfin` shared-chat composer. It sends only selected display titles, requires confirmation for every send, and does not enable automatic delivery. No live message was sent during release verification.

AniList has temporarily disabled its public API because of stability problems. Until AniList restores it, Add Anime and live refresh cannot complete; Anime Tracker now reports that upstream condition truthfully, preserves entered search text, and continues to show clearly marked cached data.
