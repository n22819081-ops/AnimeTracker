# Existing Profile Adoption

The one-time workflow detects the project-local modern profile and requires explicit confirmation. It creates a verified online pre-adoption backup, copies through a staging directory, verifies database/file hashes, schema, counts, `integrity_check`, `foreign_key_check`, mappings, rejections, candidates, outbox, and redacted DPAPI retrieval, then atomically adopts the target.

The packaged application checks the absolute Windows path `C:\AnimeTracker\Modern Anime Tracker\production_profile` regardless of its installation directory or current working directory. Before enabling adoption or project-local use, it opens the database read-only and validates integrity, foreign keys, schema compatibility, business-data counts, and redacted credential state. A missing `bootstrap.json` does not hide an otherwise valid database; bootstrap presence is reported separately.

For the current profile, preview reports 69 active titles, 421 archived/orphaned records, 1,312 shared-announcement baseline rows, eight open review cases, one mapping, 11 rejections, 27 candidates, and zero outbox rows. The first-run screen displays the detected source path and summary without creating directories or changing any source file.

The source remains intact as rollback. Nothing is moved or deleted. If a DPAPI blob cannot be decrypted under the current Windows user, it is preserved, delivery stays disabled, and the credential is marked for re-entry. No test Discord message is sent.

**Use Project-Local Profile for Now** opens the source directly without copying or deleting it. It does not change notification activation, send Discord messages, or install a scheduled task. **Review Existing Profile Adoption** shows source/target paths and counts, then requires a second explicit confirmation before backup/copy/switch operations begin.
