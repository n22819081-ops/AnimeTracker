# Notification Retry Policy

Retryable conditions are timeout, connection error, and HTTP 429, 500, 502, 503, or 504. HTTP 400, 401, 403, and 404 are permanent. Missing credentials, malformed payloads, and payloads that remain invalid after compaction are permanent.

Backoff intervals are 1 minute, 5 minutes, 15 minutes, 1 hour, and 6 hours with plus or minus 10 percent jitter. Discord `retry_after` can extend the delay. After five scheduled retries, the next failure becomes `FAILED_PERMANENT`.

A retryable failure has no delivered timestamp and remains claimable only after `next_attempt_at`. Permanent and exhausted failures remain auditable. Response bodies and headers are not stored; metadata is limited to safe status and split-part counts.
