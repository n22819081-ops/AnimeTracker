from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping

from ...domain.enums import MediaKind, RelationDirection, RelationType
from .airing import parse_airing_rows
from .cache import AniListCache
from .cancellation import Cancellation
from .client import AniListGraphQLClient
from .errors import AniListErrorType, AniListServiceError
from .models import (
    AniListAiringEpisode,
    AniListMedia,
    AniListRefreshBatch,
    AniListRefreshResult,
    AniListRelation,
    CacheRecord,
    CacheState,
    FranchiseGraph,
    FranchiseGroupSuggestion,
    RateLimitState,
    parse_anilist_status,
    parse_media,
    parse_media_kind,
    parse_relation_type,
)
from .queries import RECENT_AIRING_QUERY, UPCOMING_AIRING_QUERY, MEDIA_BY_ID_QUERY, MEDIA_PAGE_QUERY
from .refresh import build_refresh_batch
from .relations import build_franchise_graph, suggest_franchise_groups
from .search import AniListSearch, parse_search_input


class AniListService:
    def __init__(
        self,
        cache: AniListCache,
        client: AniListGraphQLClient,
        *,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.cache = cache
        self.client = client
        self.search = AniListSearch(client)
        self.clock = clock

    def get_media(
        self,
        anilist_id: int,
        *,
        force_refresh: bool = False,
        offline: bool = False,
        token: Cancellation | None = None,
        cache_connection: sqlite3.Connection | None = None,
    ) -> AniListRefreshResult:
        started = self.clock()
        if not isinstance(anilist_id, int) or anilist_id <= 0:
            return AniListRefreshResult(
                int(anilist_id) if isinstance(anilist_id, int) else 0,
                False, False, False, None, AniListErrorType.INVALID_INPUT.value,
                "AniList ID must be a positive integer.", started_at=started, completed_at=self.clock(),
            )
        cached = self.cache.get_media(anilist_id, started)
        if cached.state == CacheState.FRESH and not force_refresh:
            return AniListRefreshResult(anilist_id, True, True, False, cached.media, started_at=started, completed_at=self.clock())
        if offline:
            if cached.media:
                return AniListRefreshResult(
                    anilist_id, True, True, False, cached.media,
                    AniListErrorType.OFFLINE_CACHE_USED.value,
                    "AniList is offline; cached metadata was used.", True,
                    started_at=started, completed_at=self.clock(), stale_cache_used=cached.state != CacheState.FRESH,
                )
            error_type = AniListErrorType.CACHE_CORRUPT if cached.state == CacheState.CORRUPT else AniListErrorType.CONNECTION_ERROR
            return AniListRefreshResult(
                anilist_id, False, False, False, None, error_type.value,
                "No usable cached AniList metadata is available offline.", True,
                started_at=started, completed_at=self.clock(),
            )
        if token and token.is_cancelled():
            return AniListRefreshResult(
                anilist_id, False, False, False, None, AniListErrorType.CANCELED.value,
                "AniList operation was canceled.", started_at=started, completed_at=self.clock(), canceled=True,
            )
        try:
            response = self.client.execute(MEDIA_BY_ID_QUERY, {"id": anilist_id}, token=token)
            self.cache.save_request_state(response.rate_limit_state, self.clock())
            payload = response.data.get("Media")
            if not isinstance(payload, Mapping):
                raise AniListServiceError(AniListErrorType.NOT_FOUND, "AniList media was not found.")
            media = parse_media(payload, self.clock())
            if media.anilist_id != anilist_id:
                raise AniListServiceError(AniListErrorType.MALFORMED_RESPONSE, "AniList returned a different media identity.", False)
            self.cache.put_media(media, self.clock(), connection=cache_connection)
            return AniListRefreshResult(
                anilist_id, True, False, True, media,
                rate_limit_state=response.rate_limit_state,
                started_at=started, completed_at=self.clock(),
                network_request_count=response.network_requests,
                rate_limit_pause_count=response.rate_limit_pauses,
            )
        except AniListServiceError as error:
            completed = self.clock()
            self.cache.record_failure(anilist_id, completed, error.error_type.value, error.safe_message)
            if cached.media:
                return AniListRefreshResult(
                    anilist_id, True, True, True, cached.media,
                    AniListErrorType.OFFLINE_CACHE_USED.value,
                    "AniList refresh failed; previously valid cached metadata was retained.",
                    error.retryable, self.client.rate_limit_state, started, completed,
                    stale_cache_used=True, network_request_count=self.client.last_network_requests,
                    rate_limit_pause_count=self.client.last_rate_limit_pauses,
                )
            return AniListRefreshResult(
                anilist_id, False, False, self.client.last_network_requests > 0, None,
                error.error_type.value, error.safe_message, error.retryable,
                self.client.rate_limit_state, started, completed,
                canceled=error.error_type == AniListErrorType.CANCELED,
                network_request_count=self.client.last_network_requests,
                rate_limit_pause_count=self.client.last_rate_limit_pauses,
            )

    def refresh_media(self, anilist_id: int, *, token: Cancellation | None = None) -> AniListRefreshResult:
        return self.get_media(anilist_id, force_refresh=True, token=token)

    def refresh_batch(
        self,
        anilist_ids: Iterable[int],
        *,
        force_refresh: bool = False,
        token: Cancellation | None = None,
        archived_ids: Iterable[int] = (),
        include_archived: bool = False,
        batch_id: str | None = None,
    ) -> AniListRefreshBatch:
        requested = tuple(dict.fromkeys(int(item) for item in anilist_ids if int(item) > 0))
        archived = set(archived_ids)
        eligible = tuple(item for item in requested if include_archived or item not in archived)
        prefetched = self.cache.get_many_media(eligible, self.clock()) if not force_refresh else {}

        def refresh_one(item: int) -> AniListRefreshResult:
            record = prefetched.get(item)
            if record and record.state == CacheState.FRESH:
                now = self.clock()
                return AniListRefreshResult(item, True, True, False, record.media, started_at=now, completed_at=now)
            return self.get_media(item, force_refresh=force_refresh, token=token)

        batch = build_refresh_batch(
            requested,
            refresh_one,
            started_at=self.clock(), completed_at=self.clock, token=token,
            archived_ids=archived, include_archived=include_archived, batch_id=batch_id,
        )
        self.cache.save_batch(batch)
        return batch

    def search_media(
        self,
        value: str | int,
        *,
        year: int | None = None,
        media_format: MediaKind | None = None,
        season: str | None = None,
        page: int = 1,
        per_page: int = 20,
        limit: int = 50,
        offline: bool = False,
        token: Cancellation | None = None,
    ) -> tuple[AniListMedia, ...]:
        parsed = parse_search_input(value)
        if parsed.kind != "TITLE":
            if offline and parsed.kind == "ANILIST_ID":
                cached = self.cache.get_media(int(parsed.value), self.clock())
                return (cached.media,) if cached.media else ()
            media = self.search.exact_lookup(parsed, token)
            self.cache.save_request_state(self.client.rate_limit_state, self.clock())
            self.cache.put_media(media, self.clock())
            return (media,)
        if offline:
            return self.cache.search_cached_titles(str(parsed.value), limit)
        results = self.search.search_title(
            str(parsed.value), year=year, media_format=media_format, season=season,
            page=page, per_page=per_page, limit=limit, token=token,
        )
        now = self.clock()
        self.cache.save_request_state(self.client.rate_limit_state, now)
        for media in results:
            self.cache.put_media(media, now)
        return results

    def get_media_page(
        self,
        anilist_ids: Iterable[int],
        *,
        page: int = 1,
        per_page: int = 50,
        token: Cancellation | None = None,
    ) -> tuple[AniListMedia, ...]:
        if page <= 0 or per_page <= 0:
            raise AniListServiceError(AniListErrorType.INVALID_INPUT, "Pagination values must be positive.")
        ids = tuple(dict.fromkeys(int(item) for item in anilist_ids if int(item) > 0))
        response = self.client.execute(
            MEDIA_PAGE_QUERY,
            {"ids": list(ids), "page": page, "perPage": min(50, max(1, per_page))},
            token=token,
        )
        page_data = response.data.get("Page") or {}
        rows = page_data.get("media") or []
        if not isinstance(rows, list):
            raise AniListServiceError(AniListErrorType.MALFORMED_RESPONSE, "AniList media page was malformed.", True)
        values = tuple(parse_media(row, self.clock()) for row in rows)
        now = self.clock()
        for media in values:
            self.cache.put_media(media, now)
        self.cache.save_request_state(response.rate_limit_state, now)
        return values

    def get_cache_status(self, anilist_id: int) -> CacheRecord:
        return self.cache.get_media(anilist_id, self.clock())

    def invalidate_cache(self, anilist_id: int) -> bool:
        return self.cache.invalidate(anilist_id, self.clock())

    def get_relations(self, anilist_id: int, *, offline: bool = False) -> tuple[AniListRelation, ...]:
        relation_cache = self.cache.get_relations(anilist_id, self.clock())
        if relation_cache.state != CacheState.MISS and (offline or relation_cache.state == CacheState.FRESH):
            return relation_cache.relations
        record = self.cache.get_media(anilist_id, self.clock())
        if record.media and (offline or record.media.relations):
            return record.media.relations
        result = self.get_media(anilist_id, force_refresh=True, offline=offline)
        return result.updated_data.relations if result.updated_data else ()

    def get_franchise_graph(self, anilist_ids: Iterable[int], *, offline: bool = False) -> FranchiseGraph:
        ids = tuple(dict.fromkeys(anilist_ids))
        relations = tuple(relation for media_id in ids for relation in self.get_relations(media_id, offline=offline))
        graph = build_franchise_graph(relations, ids)
        media = {item: record.media for item in ids if (record := self.cache.get_media(item, self.clock())).media is not None}
        self.cache.put_franchise_graph(graph, media, self.clock())
        return graph

    def get_franchise_groups(self, anilist_ids: Iterable[int], *, offline: bool = False) -> tuple[FranchiseGroupSuggestion, ...]:
        ids = tuple(dict.fromkeys(anilist_ids))
        graph = self.get_franchise_graph(ids, offline=offline)
        media = {item: record.media for item in ids if (record := self.cache.get_media(item, self.clock())).media is not None}
        groups = suggest_franchise_groups(graph, media)
        self.cache.put_franchise_groups(groups, self.clock())
        return groups

    def _get_airings(
        self,
        query: str,
        start: datetime,
        end: datetime,
        *,
        token: Cancellation | None = None,
    ) -> tuple[AniListAiringEpisode, ...]:
        rows = []
        page_number = 1
        while True:
            response = self.client.execute(query, {
                "from": int(start.timestamp()), "to": int(end.timestamp()), "page": page_number, "perPage": 50,
            }, token=token)
            self.cache.save_request_state(response.rate_limit_state, self.clock())
            page = response.data.get("Page") or {}
            page_rows = page.get("airingSchedules") or []
            if not isinstance(page_rows, list):
                raise AniListServiceError(AniListErrorType.MALFORMED_RESPONSE, "AniList airing schedule was malformed.", True)
            rows.extend(page_rows)
            if not (page.get("pageInfo") or {}).get("hasNextPage") or not page_rows:
                break
            page_number += 1
        episodes = parse_airing_rows(rows, self.clock())
        grouped: dict[int, list[AniListAiringEpisode]] = {}
        for item in episodes:
            grouped.setdefault(item.media_id, []).append(item)
        for media_id, values in grouped.items():
            self.cache.put_airing_schedule(media_id, tuple(values), self.clock())
        return episodes

    def get_upcoming_airings(self, *, days: int = 7, token: Cancellation | None = None) -> tuple[AniListAiringEpisode, ...]:
        now = self.clock()
        return self._get_airings(UPCOMING_AIRING_QUERY, now, now + timedelta(days=days), token=token)

    def get_recent_airings(self, *, days: int = 7, token: Cancellation | None = None) -> tuple[AniListAiringEpisode, ...]:
        now = self.clock()
        return self._get_airings(RECENT_AIRING_QUERY, now - timedelta(days=days), now, token=token)

    def get_airing_schedule(self, anilist_id: int, *, offline: bool = False) -> tuple[AniListAiringEpisode, ...]:
        cached = self.cache.get_airing_schedule_record(anilist_id, self.clock())
        if offline or cached.state == CacheState.FRESH:
            return cached.episodes
        recent = self.get_recent_airings()
        upcoming = self.get_upcoming_airings()
        return tuple(item for item in (*recent, *upcoming) if item.media_id == anilist_id)

    def get_airing_schedule_cache_status(self, anilist_id: int):
        return self.cache.get_airing_schedule_record(anilist_id, self.clock())
