from __future__ import annotations

import logging
import re
import time
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)
ANILIST_URL = "https://graphql.anilist.co"

MEDIA_FIELDS = """
id
title { romaji english native }
synonyms
format
season
seasonYear
episodes
status
startDate { year month day }
endDate { year month day }
coverImage { large medium }
siteUrl
relations {
  edges {
    relationType
    node {
      id
      format
      status
      title { romaji english native }
    }
  }
}
"""

HEALTH_CHECK_QUERY = """
query {
  Media(id: 1, type: ANIME) {
    id
    title { romaji }
  }
}
"""


class AniListError(RuntimeError):
    pass


class AniListClient:
    def __init__(self, timeout: int = 20, retries: int = 3) -> None:
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()

    def get_by_id(self, anilist_id: int) -> dict[str, Any]:
        query = f"""
        query ($id: Int) {{
          Media(id: $id, type: ANIME) {{
            {MEDIA_FIELDS}
          }}
        }}
        """
        data = self._post(query, {"id": anilist_id})
        media = data.get("Media")
        if not media:
            raise AniListError(f"AniList anime ID {anilist_id} was not found.")
        return media

    def search(self, title: str, per_page: int = 8) -> list[dict[str, Any]]:
        query = f"""
        query ($search: String, $perPage: Int) {{
          Page(page: 1, perPage: $perPage) {{
            media(search: $search, type: ANIME) {{
              {MEDIA_FIELDS}
            }}
          }}
        }}
        """
        data = self._post(query, {"search": title, "perPage": per_page})
        return (data.get("Page") or {}).get("media") or []

    def health_check(self, timeout: float = 8.0) -> tuple[bool, str]:
        """Manually check whether the AniList GraphQL API is reachable.

        Performs a single lightweight public query (no authentication) with a
        short timeout and no retries. Returns ``(online, detail)`` where
        ``online`` is True only for a usable API response: HTTP 200, valid
        JSON, no GraphQL errors, and a ``Media`` entry present. Rate limiting
        (HTTP 429) is deliberately reported as offline, not success. The
        ``detail`` string is a short human-readable reason and never contains
        credentials.
        """
        try:
            response = self.session.post(
                ANILIST_URL,
                json={"query": HEALTH_CHECK_QUERY, "variables": {}},
                timeout=timeout,
            )
        except requests.RequestException as exc:
            detail = f"{type(exc).__name__}: {exc}".strip()
            LOGGER.warning("AniList health check failed: %s", detail)
            return False, detail
        if response.status_code == 429:
            return False, "AniList is rate limiting requests (HTTP 429)"
        if response.status_code != 200:
            return False, f"AniList returned HTTP {response.status_code}"
        try:
            payload = response.json()
        except ValueError:
            return False, "AniList returned a non-JSON response"
        if not isinstance(payload, dict) or payload.get("errors"):
            return False, "AniList returned an error response"
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("Media"), dict):
            return False, "AniList returned an unusable response"
        LOGGER.info("AniList health check passed")
        return True, "AniList responded to the health check query"

    def _post(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.post(
                    ANILIST_URL,
                    json={"query": query, "variables": variables},
                    timeout=self.timeout,
                )
                if response.status_code == 429:
                    wait = int(response.headers.get("Retry-After", "3"))
                    LOGGER.warning("AniList rate limited request; waiting %s seconds", wait)
                    time.sleep(wait)
                    continue
                response.raise_for_status()
                payload = response.json()
                if payload.get("errors"):
                    raise AniListError(str(payload["errors"]))
                return payload.get("data") or {}
            except (requests.RequestException, ValueError, AniListError) as exc:
                last_error = exc
                LOGGER.warning("AniList request attempt %s failed: %s", attempt, exc)
                if attempt < self.retries:
                    time.sleep(1.5 * attempt)
        raise AniListError(f"AniList request failed: {last_error}")


def parse_anilist_input(value: str) -> int | str:
    text = (value or "").strip()
    match = re.search(r"anilist\.co/anime/(\d+)", text, re.IGNORECASE)
    if match:
        return int(match.group(1))
    if text.isdigit():
        return int(text)
    return text
