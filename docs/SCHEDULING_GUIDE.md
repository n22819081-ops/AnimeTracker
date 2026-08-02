# Scheduling

The packaged command is `Anime Tracker.exe --scheduled-check --profile "<absolute profile path>"`. It acquires a single-run lock, creates a backup, applies enabled refresh/scan stages, respects notification activation, records a structured result, and exits with a status code. Stage 1 never delivers Discord messages.

Scheduling is opt-in. The GUI can request installation of a separately named `Anime Tracker Modern - Validation` task through UAC. Its action calls the packaged EXE directly, uses `RunLevel Limited`, ignores overlapping starts, and never changes the existing legacy task. Resolve the legacy task deliberately before enabling production delivery in a modern task.
