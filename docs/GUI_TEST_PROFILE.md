# Modern Test Profile

The default profile is `C:\AnimeTracker\modern_profile_test`. On first launch it copies `migration_test\anime_tracker_modern_v5.db` to `modern_profile_test\data\anime_tracker_modern.db`. Both locations are development artifacts excluded from Git; the live `data\anime_tracker.db` is never selected as the modern writable database.

Settings default to Dark with automatic refresh, automatic scanning, and every notification channel disabled. Webhook and secret keys are removed before settings are written. Jellyfin test paths start empty, so Scan Jellyfin is blocked until the user explicitly supplies safe fixture roots.

Reset the disposable profile with:

```powershell
.\Run-AnimeTracker-Modern.ps1 --reset-profile
```

Reset never replaces or deletes the legacy database. The title bar and banner continuously identify the development profile and disabled production cutover.
