from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta


RETRY_DELAYS_SECONDS = (60, 300, 900, 3600, 21600)
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
PERMANENT_HTTP_STATUSES = {400, 401, 403, 404}


@dataclass(frozen=True)
class RetryDecision:
    retryable: bool
    exhausted: bool
    next_attempt_at: datetime | None


def retry_decision(
    attempt_count: int,
    now: datetime,
    *,
    retry_after_seconds: float | None = None,
    jitter: bool = True,
    random_source=random.random,
) -> RetryDecision:
    if attempt_count >= len(RETRY_DELAYS_SECONDS):
        return RetryDecision(False, True, None)
    delay = max(RETRY_DELAYS_SECONDS[attempt_count], retry_after_seconds or 0)
    if jitter:
        delay *= 0.9 + random_source() * 0.2
    return RetryDecision(True, False, now + timedelta(seconds=delay))
