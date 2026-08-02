# AniList Cache Policy

## Metadata Expiration

| Data | Default TTL |
|---|---:|
| Finished media metadata | 30 days |
| Releasing media metadata | 1 hour |
| Upcoming media metadata | 6 hours |
| Upcoming within 14 days of known start | 1 hour |
| Unknown/cancelled/other metadata | 6 hours |
| Relations | 7 days |
| Airing schedule snapshots | 15 minutes |

All expiration comparisons use timezone-aware UTC. Finished metadata receives a longer TTL because identity and release facts are comparatively stable. AniList supplies no useful ETag for these public GraphQL operations, so the schema reserves provider metadata without inventing one.

## States

- `MISS`: no snapshot exists.
- `FRESH`: valid snapshot before expiration.
- `STALE`: valid snapshot remains available after expiration and is eligible for refresh.
- `CORRUPT`: the stored normalized payload cannot be parsed; it is reported and not silently converted to empty metadata.

Forced refresh ignores freshness. Offline mode returns valid fresh or stale data and marks stale fallback explicitly. A failed request increments failure evidence, marks the snapshot stale, and retains the last successful payload. Empty relation and schedule snapshots have separate state rows, so “known empty” is distinct from “not cached.”

Per-record invalidation marks only one media record stale. Full clear is restricted to explicitly constructed test profiles and deletes only AniList cache/batch/graph data. It does not delete tracked media, mappings, overrides, rejections, status history, or notification history.
