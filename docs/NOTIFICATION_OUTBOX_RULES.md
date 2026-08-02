# Notification Outbox Rules

States are `PENDING`, `CLAIMED`, `DELIVERED`, `RETRY_WAIT`, `FAILED_PERMANENT`, `CANCELED`, `SUPPRESSED`, and `EXPIRED`.

Enqueue stores the event and channel-specific message in one SQLite transaction. Stable deduplication constraints prevent repeated processing from creating duplicate active work. Suppressed events remain recorded with a reason.

Workers claim eligible rows under `BEGIN IMMEDIATE`, set worker identity and lease expiration, commit, then perform network I/O. Completion must match both worker identity and claimed state. Expired claims are recoverable. Delivered rows are never eligible again. Every attempted delivery creates an immutable result row.

Batch health is `SUCCESS`, `PARTIAL_SUCCESS`, `FAILED`, or `NO_WORK` and reports total, enqueued, suppressed, delivered, retry pending, permanent failure, and canceled counts. A normal process exit cannot conceal mixed outcomes.
