from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from anime_tracker.services.anilist.cache import AniListCache
from anime_tracker.services.anilist.client import AniListGraphQLClient
from anime_tracker.services.anilist.rate_limit import RetryPolicy

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "anilist"
NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def fixture(name: str) -> Any:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, status_code=200, body=None, headers=None, json_error: Exception | None = None):
        self.status_code = status_code
        self.body = body
        self.headers = headers or {}
        self.json_error = json_error

    def json(self):
        if self.json_error:
            raise self.json_error
        return self.body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if callable(response):
            response = response()
        if isinstance(response, Exception):
            raise response
        return response


def media_response(media):
    return FakeResponse(200, {"data": {"Media": media}}, {"X-RateLimit-Limit": "90", "X-RateLimit-Remaining": "89"})


def page_response(media, *, has_next=False, page=1):
    return FakeResponse(200, {"data": {"Page": {"pageInfo": {"hasNextPage": has_next, "currentPage": page}, "media": media}}})


def client_for(responses, *, retries=0, sleep=lambda _seconds: None):
    session = FakeSession(responses)
    client = AniListGraphQLClient(
        session=session,
        retry_policy=RetryPolicy(maximum_retries=retries),
        sleep=sleep,
        clock=lambda: NOW,
        random_value=lambda: 0.5,
    )
    return client, session


def make_cache(path: Path) -> AniListCache:
    return AniListCache(path, test_profile=True, create=True)
