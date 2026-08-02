from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Callable, Iterable
from uuid import uuid4

from .cancellation import CancellationToken
from .models import AniListRefreshBatch, AniListRefreshResult, BatchState, RateLimitState


def build_refresh_batch(
    requested_ids: Iterable[int],
    refresh_one: Callable[[int], AniListRefreshResult],
    *,
    started_at: datetime,
    completed_at: Callable[[], datetime],
    token: CancellationToken | None = None,
    archived_ids: Iterable[int] = (),
    include_archived: bool = False,
    batch_id: str | None = None,
) -> AniListRefreshBatch:
    archived = set(archived_ids)
    unique = tuple(dict.fromkeys(int(item) for item in requested_ids if int(item) > 0))
    eligible = tuple(item for item in unique if include_archived or item not in archived)
    results: list[AniListRefreshResult] = []
    for index, media_id in enumerate(eligible):
        if token and token.is_canceled:
            now = completed_at()
            results.extend(
                AniListRefreshResult(
                    remaining, False, False, False, None, "CANCELED", "AniList refresh was canceled.",
                    False, RateLimitState(), now, now, canceled=True,
                )
                for remaining in eligible[index:]
            )
            break
        results.append(refresh_one(media_id))

    succeeded = sum(item.success for item in results)
    canceled = sum(item.canceled for item in results)
    failed = sum(not item.success and not item.canceled for item in results)
    degraded = sum(item.success and (item.stale_cache_used or bool(item.error_type)) for item in results)
    if canceled and succeeded == 0 and failed == 0:
        state = BatchState.CANCELED
    elif failed == 0 and canceled == 0 and degraded == 0:
        state = BatchState.SUCCESS
    elif succeeded > 0:
        state = BatchState.PARTIAL_FAILURE
    else:
        state = BatchState.FAILED if failed else BatchState.CANCELED
    errors = Counter(item.error_type for item in results if item.error_type and not item.canceled)
    return AniListRefreshBatch(
        batch_id or f"refresh-{uuid4().hex}",
        eligible,
        started_at,
        completed_at(),
        len(eligible),
        succeeded,
        failed,
        sum(item.cache_hit for item in results),
        sum(item.network_request_count or int(item.network_request_performed) for item in results),
        sum(item.rate_limit_pause_count or int(item.rate_limit_state.paused) for item in results),
        canceled,
        state,
        tuple(sorted(errors.items())),
        tuple(results),
    )
