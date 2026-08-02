from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Mapping

from .cancellation import CancellationToken
from .models import RateLimitState


MINIMUM_RETRY_DELAY = 1.0


def _integer(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def parse_retry_after(value: object, now: datetime | None = None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    try:
        seconds = float(text)
        return max(MINIMUM_RETRY_DELAY, seconds)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(MINIMUM_RETRY_DELAY, (parsed - (now or datetime.now(timezone.utc))).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def rate_limit_from_headers(headers: Mapping[str, object], now: datetime | None = None) -> RateLimitState:
    now = now or datetime.now(timezone.utc)
    limit = _integer(headers.get("X-RateLimit-Limit"))
    remaining = _integer(headers.get("X-RateLimit-Remaining"))
    raw_reset = _integer(headers.get("X-RateLimit-Reset"))
    reset_at = datetime.fromtimestamp(raw_reset, tz=timezone.utc) if raw_reset and raw_reset > 0 else None
    retry_after = parse_retry_after(headers.get("Retry-After"), now)
    return RateLimitState(limit, remaining, reset_at, retry_after, retry_after is not None or remaining == 0)


@dataclass(frozen=True)
class RetryPolicy:
    maximum_retries: int = 3
    base_delay_seconds: float = 1.0
    maximum_delay_seconds: float = 30.0
    jitter_ratio: float = 0.2

    def delay(self, attempt: int, retry_after: float | None = None, random_value: float | None = None) -> float:
        if retry_after is not None:
            return max(MINIMUM_RETRY_DELAY, min(self.maximum_delay_seconds, retry_after))
        base = min(self.maximum_delay_seconds, self.base_delay_seconds * (2 ** max(0, attempt - 1)))
        unit = random.random() if random_value is None else max(0.0, min(1.0, random_value))
        jitter = base * self.jitter_ratio * ((unit * 2.0) - 1.0)
        return max(MINIMUM_RETRY_DELAY, min(self.maximum_delay_seconds, base + jitter))


def cancellable_wait(seconds: float, token: CancellationToken | None, sleep) -> bool:
    if token is not None:
        return token.wait(seconds)
    sleep(seconds)
    return False
