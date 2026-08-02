from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .cache import AniListCache
from .client import AniListGraphQLClient
from .service import AniListService

LIVE_CHECK_IDS = (1, 5114, 16498)


@dataclass(frozen=True)
class LiveCheckResult:
    ran: bool
    requested_ids: tuple[int, ...] = ()
    successful_ids: tuple[int, ...] = ()
    failed_ids: tuple[int, ...] = ()
    message: str = ""


def run_optional_live_check() -> LiveCheckResult:
    if os.environ.get("ANIME_TRACKER_ANILIST_LIVE_CHECK") != "1":
        return LiveCheckResult(False, message="Optional AniList live check is disabled.")
    ids = LIVE_CHECK_IDS[:3]
    with tempfile.TemporaryDirectory(prefix="anime-tracker-anilist-live-") as directory:
        cache = AniListCache(Path(directory) / "cache.db", test_profile=True, create=True)
        service = AniListService(cache, AniListGraphQLClient())
        results = tuple(service.refresh_media(item) for item in ids)
    return LiveCheckResult(
        True,
        ids,
        tuple(item.anilist_id for item in results if item.success),
        tuple(item.anilist_id for item in results if not item.success),
        "Optional live check completed using only a temporary cache.",
    )
