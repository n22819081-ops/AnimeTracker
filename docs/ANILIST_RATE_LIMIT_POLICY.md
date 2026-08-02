# AniList Rate-Limit Policy

The client reads `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, and `Retry-After` when present. Low remaining capacity pauses conservatively until reset. The latest structured request state is persisted in the schema-v3 prototype.

Retry rules:

- Default maximum: three retries after the first attempt.
- Exponential base: 1 second, doubling by attempt.
- Jitter: plus or minus 20 percent.
- Maximum delay: 30 seconds.
- Explicit `Retry-After` takes precedence within the maximum.
- Missing or invalid `Retry-After` uses exponential backoff.
- Zero or negative numeric values use a one-second minimum, preventing an uncontrolled retry loop.
- Cancellation interrupts a backoff and stops further requests.

Rate limits, timeouts, connection failures, temporary 5xx responses, and explicitly temporary GraphQL errors may retry. Not-found responses, malformed input, identity mismatches, ordinary GraphQL validation failures, and cancellation do not retry. Batch accounting records actual HTTP attempts and rate-limit/backoff pauses.
