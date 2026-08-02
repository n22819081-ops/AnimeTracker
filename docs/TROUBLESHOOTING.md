# Troubleshooting

- **SmartScreen warning:** this RC is unsigned. Verify hashes; do not disable SmartScreen or antivirus globally.
- **App does not start:** extract the full onedir folder and keep `_internal` beside the EXE. Review `%LOCALAPPDATA%\Anime Tracker\AnimeTracker\logs`.
- **Credential requires re-entry:** DPAPI binds secrets to a Windows user/security state. Re-enter it; the old blob is not erased during adoption.
- **Scheduled check already running:** wait for the lock holder. Overlapping runs are intentionally rejected.
- **AniList unavailable:** cached data is retained and partial/offline status is recorded.
- **Jellyfin mismatch:** use review/manual mapping. A different season is never accepted merely because the franchise folder exists.
