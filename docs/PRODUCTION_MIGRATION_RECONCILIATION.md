# Migration Reconciliation Report

The production migration used only the verified pre-cutover backup. The legacy live database remained unchanged and the modern cutover is pending explicit approval.

## Source Reconciliation

| Legacy table | Source | Active | Archived | Excluded | Warnings | Balanced |
|---|---:|---:|---:|---:|---:|:---:|
| `anime` | 69 | 69 | 0 | 0 | 0 | Yes |
| `jellyfin_announcement_snapshot` | 1312 | 1312 | 0 | 0 | 0 | Yes |
| `manual_announcement_queue` | 0 | 0 | 0 | 0 | 0 | Yes |
| `manual_announcement_titles` | 3 | 3 | 0 | 0 | 0 | Yes |
| `match_candidates` | 114 | 14 | 100 | 0 | 0 | Yes |
| `notification_events` | 0 | 0 | 0 | 0 | 0 | Yes |
| `rejected_matches` | 19 | 11 | 8 | 0 | 0 | Yes |
| `server_matches` | 93 | 1 | 92 | 0 | 0 | Yes |
| `settings` | 16 | 16 | 0 | 0 | 0 | Yes |
| `status_history` | 374 | 153 | 221 | 0 | 0 | Yes |

- Unexplained-loss tables: 0
- Preserved unresolved archival records: 421
- Shared library paths with multiple active mappings: 0
- Source hash unchanged: True
- Live database hash unchanged: True

## Orphan And Duplicate Handling

Orphans, malformed identities, and duplicate AniList IDs are retained as complete JSON payloads in `archived_legacy_records`. No title/path similarity is used to assign ownership. Every such row is marked `Manual review required`.

## Sample Validation

- AniList ID `355`: provider identity and tracked row preserved.
- AniList ID `2526`: provider identity and tracked row preserved.
- AniList ID `5081`: provider identity and tracked row preserved.
- AniList ID `18677`: provider identity and tracked row preserved.
- AniList ID `20943`: provider identity and tracked row preserved.

## Production Validation

- Active Titles: 69
- Archived Orphans: 421
- Shared Baselines: 1312
- Mappings: 1
- Rejections: 11
- Candidates: 14
- Foreign Key Violations: 0
- Integrity check: ok
- Cutover: pending explicit approval
- Credential migration: completed to 2 separate disabled DPAPI references; legacy JSON retained
- Notification stage: 1 (preview only)
