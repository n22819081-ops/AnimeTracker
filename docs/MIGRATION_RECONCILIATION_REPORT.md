# Migration Reconciliation Report

The prototype used only the verified backup. It did not replace or migrate the live application database.

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
