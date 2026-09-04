# Scheduling Cutover

The production command is:

```powershell
.\.venv\Scripts\pythonw.exe -m anime_tracker.production.scheduled_command --profile "Modern Anime Tracker\production_profile"
```

It acquires a cross-process lock, creates a verified scheduled backup, runs only enabled stages, records structured counts, and returns `SUCCESS`, `PARTIAL_SUCCESS`, `FAILED`, `ALREADY_RUNNING`, or `OFFLINE_CACHE_ONLY`.

`Modern Anime Tracker\Create-ModernScheduledTask.ps1` registers the separate `Anime Tracker Modern - Validation` task with `RunLevel Limited`, `StartWhenAvailable`, and `MultipleInstances IgnoreNew`. It was not invoked. The legacy `Anime Tracker Weekly Check` remains Ready and was not disabled. Production task cutover is pending explicit approval and manual validation.
