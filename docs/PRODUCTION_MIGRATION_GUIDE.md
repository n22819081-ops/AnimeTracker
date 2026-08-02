# Production Migration Guide

1. Verify no legacy writer is active and inspect the legacy scheduled task read-only.
2. Create an online SQLite backup, byte copy, config/log backup, task export, hashes, integrity check, and manifest.
3. Migrate only from the verified online backup into a temporary modern database.
4. Apply schemas v1, v3, v4, v5, and v6, reconciling v1 before matching-table conversion.
5. Validate exact counts, foreign keys, integrity, and absence of raw webhooks.
6. Atomically rename the completed database into `production_profile`.
7. Run AniList baseline, read-only inventory, suggestion-only matching, backup/restore validation, and legacy-modern comparison.
8. Leave cutover pending until the exact approval phrase is supplied.

Migration is restart-aware. A completed `MIGRATED_PENDING_CUTOVER` database is validated and reused; an interrupted temporary database is never promoted.
