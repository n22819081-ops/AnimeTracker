# Live AniList Integration

The production GUI uses the modern official-endpoint GraphQL client, cache, sequential refresh batches, rate-limit handling, cancellation, stale-cache fallback, airing schedules, relations, and franchise data. Local paths and webhook values are rejected from request variables.

Controlled validation previewed 69 unique active IDs, refreshed three successfully, then completed a cache-first baseline of all 69: 69 succeeded, 0 failed, 69 cache hits on the verification pass, and 0 notification events. Archived titles were excluded. A missing-date adapter defect found during validation was corrected so unknown dates remain empty legacy-compatible values rather than SQL nulls.
