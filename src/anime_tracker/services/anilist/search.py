from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .cancellation import Cancellation
from .client import AniListGraphQLClient
from .errors import AniListErrorType, AniListServiceError
from .models import AniListMedia, MediaKind, parse_media
from .queries import MEDIA_BY_ID_QUERY, MEDIA_BY_MAL_ID_QUERY, MEDIA_SEARCH_QUERY

ANILIST_URL_PATTERN = re.compile(r"^https?://(?:www\.)?anilist\.co/anime/(\d+)(?:/[^?#]*)?(?:[?#].*)?$", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedSearchInput:
    kind: str
    value: int | str


def parse_search_input(value: str | int) -> ParsedSearchInput:
    if isinstance(value, int):
        if value <= 0:
            raise AniListServiceError(AniListErrorType.INVALID_INPUT, "AniList ID must be positive.")
        return ParsedSearchInput("ANILIST_ID", value)
    text = str(value or "").strip()
    if not text:
        raise AniListServiceError(AniListErrorType.INVALID_INPUT, "Enter an AniList ID, URL, MAL ID, or title.")
    match = ANILIST_URL_PATTERN.match(text)
    if match:
        return ParsedSearchInput("ANILIST_ID", int(match.group(1)))
    if text.isdigit():
        return ParsedSearchInput("ANILIST_ID", int(text))
    mal_match = re.fullmatch(r"(?:mal|myanimelist)\s*[:#]?\s*(\d+)", text, re.IGNORECASE)
    if mal_match:
        return ParsedSearchInput("MAL_ID", int(mal_match.group(1)))
    if text.startswith("http://") or text.startswith("https://"):
        raise AniListServiceError(AniListErrorType.INVALID_INPUT, "The URL is not a valid AniList anime URL.")
    return ParsedSearchInput("TITLE", text)


class AniListSearch:
    def __init__(self, client: AniListGraphQLClient) -> None:
        self.client = client

    def exact_lookup(self, parsed: ParsedSearchInput, token: Cancellation | None = None) -> AniListMedia:
        query = MEDIA_BY_MAL_ID_QUERY if parsed.kind == "MAL_ID" else MEDIA_BY_ID_QUERY
        key = "malId" if parsed.kind == "MAL_ID" else "id"
        result = self.client.execute(query, {key: int(parsed.value)}, token=token)
        payload = result.data.get("Media")
        if not isinstance(payload, Mapping):
            raise AniListServiceError(AniListErrorType.NOT_FOUND, "AniList media was not found.")
        return parse_media(payload)

    def search_title(
        self,
        title: str,
        *,
        year: int | None = None,
        media_format: MediaKind | None = None,
        season: str | None = None,
        page: int = 1,
        per_page: int = 20,
        limit: int = 50,
        token: Cancellation | None = None,
    ) -> tuple[AniListMedia, ...]:
        if page <= 0 or per_page <= 0 or limit <= 0:
            raise AniListServiceError(AniListErrorType.INVALID_INPUT, "Pagination values must be positive.")
        results: list[AniListMedia] = []
        seen: set[int] = set()
        current_page = page
        while len(results) < limit:
            variables = {
                "search": title,
                "page": current_page,
                "perPage": min(per_page, 50),
                "year": year,
                "format": media_format.value if media_format else None,
                "season": season.upper() if season else None,
            }
            response = self.client.execute(MEDIA_SEARCH_QUERY, variables, token=token)
            page_data = response.data.get("Page") or {}
            media_rows = page_data.get("media") or []
            if not isinstance(media_rows, list):
                raise AniListServiceError(AniListErrorType.MALFORMED_RESPONSE, "AniList search results were malformed.", True)
            for payload in media_rows:
                media = parse_media(payload)
                if media.anilist_id not in seen:
                    seen.add(media.anilist_id)
                    results.append(media)
                    if len(results) >= limit:
                        break
            info = page_data.get("pageInfo") or {}
            if not info.get("hasNextPage") or not media_rows:
                break
            current_page += 1
        return tuple(results)
