# Live Jellyfin Scan Rules

The production action is labeled `Scan Jellyfin Libraries - Read Only`. It requires explicit confirmation and displays both configured roots. Scanning is background-capable, cancellable, skips links/junctions, uses metadata reads only, and persists only complete snapshots. Partial or inaccessible roots retain the prior complete snapshot, do not replace the last valid snapshot, and do not regenerate candidates from incomplete evidence.

Controlled live result:

- Movies Library: complete, 176 items, 0 diagnostics
- TV Library: complete, 411 items, 37 nonfatal diagnostics
- Directories seen: 962
- Files seen: 12,335
- Media files classified: 10,843
- Auto-confirmed mappings: 0
- Notification events: 0
- End-to-end duration: 6.67 seconds

After the complete snapshot commits, suggestion-only matching evaluates all 69 active titles, applies persistent rejections and manual decisions, and generates 13 suggestions across 12 titles. Candidate/session identity is persisted and migrated candidate-driven reviews are relinked. Candidate-only reviews not reproduced by the complete scan are superseded; zero candidates alone never creates Needs Review. The migrated unknown-scope mapping is revalidated, remains unresolved, and cannot prove season coverage. It is never auto-confirmed or silently replaced.
