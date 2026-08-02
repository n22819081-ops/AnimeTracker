from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping

from ...domain.enums import AniListStatus, MediaKind, RelationDirection, RelationType


class DigitalAvailability(str, Enum):
    UNKNOWN = "UNKNOWN"
    CONFIRMED = "CONFIRMED"


class CacheState(str, Enum):
    MISS = "MISS"
    FRESH = "FRESH"
    STALE = "STALE"
    CORRUPT = "CORRUPT"


class BatchState(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class AiringEventType(str, Enum):
    NEW_EPISODE_AIRED = "NEW_EPISODE_AIRED"
    NEXT_EPISODE_SCHEDULED = "NEXT_EPISODE_SCHEDULED"
    AIRING_TIME_CHANGED = "AIRING_TIME_CHANGED"
    EPISODE_DELAYED = "EPISODE_DELAYED"
    AIRING_SCHEDULE_REMOVED = "AIRING_SCHEDULE_REMOVED"
    SEASON_STARTED_AIRING = "SEASON_STARTED_AIRING"
    SERIES_FINISHED_AIRING = "SERIES_FINISHED_AIRING"


@dataclass(frozen=True)
class AniListTitle:
    primary: str
    english: str = ""
    romaji: str = ""
    native: str = ""
    synonyms: tuple[str, ...] = ()

    @property
    def variants(self) -> tuple[str, ...]:
        values = (self.primary, self.english, self.romaji, self.native, *self.synonyms)
        return tuple(dict.fromkeys(item for item in values if item))


@dataclass(frozen=True)
class CoverImages:
    extra_large: str = ""
    large: str = ""
    medium: str = ""
    color: str = ""


@dataclass(frozen=True)
class AniListAiringEpisode:
    media_id: int
    episode_number: int
    airing_at: datetime
    time_until_airing: int | None = None
    has_aired: bool = False
    schedule_id: int | None = None


@dataclass(frozen=True)
class AiringScheduleSummary:
    previous_episode: AniListAiringEpisode | None = None
    next_episode: AniListAiringEpisode | None = None
    recent: tuple[AniListAiringEpisode, ...] = ()
    upcoming: tuple[AniListAiringEpisode, ...] = ()


@dataclass(frozen=True)
class AniListRelation:
    source_anilist_id: int
    target_anilist_id: int | None
    relation_type: RelationType
    target_format: MediaKind = MediaKind.UNKNOWN
    target_status: AniListStatus = AniListStatus.UNKNOWN
    target_title: str = ""
    direction: RelationDirection = RelationDirection.OUTBOUND
    provider: str = "AniList"
    retrieved_at: datetime | None = None
    legacy_label: str = ""
    provider_confirmed: bool = True


@dataclass(frozen=True)
class AniListMedia:
    anilist_id: int
    mal_id: int | None
    title: AniListTitle
    media_format: MediaKind
    status: AniListStatus
    season: str = ""
    season_year: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    episode_count: int | None = None
    duration_minutes: int | None = None
    country_of_origin: str = ""
    source: str = ""
    genres: tuple[str, ...] = ()
    average_score: int | None = None
    popularity: int | None = None
    cover_images: CoverImages = CoverImages()
    banner_image_url: str = ""
    site_url: str = ""
    description: str = ""
    is_adult: bool = False
    provider_updated_at: int | None = None
    next_airing_episode: AniListAiringEpisode | None = None
    airing_schedule: AiringScheduleSummary = AiringScheduleSummary()
    relations: tuple[AniListRelation, ...] = ()
    digital_availability: DigitalAvailability = DigitalAvailability.UNKNOWN


@dataclass(frozen=True)
class RateLimitState:
    limit: int | None = None
    remaining: int | None = None
    reset_at: datetime | None = None
    retry_after_seconds: float | None = None
    paused: bool = False


@dataclass(frozen=True)
class AniListRefreshResult:
    anilist_id: int
    success: bool
    cache_hit: bool
    network_request_performed: bool
    updated_data: AniListMedia | None
    error_type: str = ""
    error_message: str = ""
    retryable: bool = False
    rate_limit_state: RateLimitState = RateLimitState()
    started_at: datetime | None = None
    completed_at: datetime | None = None
    stale_cache_used: bool = False
    canceled: bool = False
    network_request_count: int = 0
    rate_limit_pause_count: int = 0


@dataclass(frozen=True)
class AniListRefreshBatch:
    batch_id: str
    requested_anilist_ids: tuple[int, ...]
    started_at: datetime
    completed_at: datetime
    total: int
    succeeded: int
    failed: int
    cache_hits: int
    network_requests: int
    rate_limit_pauses: int
    canceled_count: int
    state: BatchState
    error_summary: tuple[tuple[str, int], ...]
    results: tuple[AniListRefreshResult, ...]

    @property
    def partial_success(self) -> bool:
        return self.state == BatchState.PARTIAL_FAILURE


@dataclass(frozen=True)
class CacheRecord:
    state: CacheState
    media: AniListMedia | None = None
    retrieved_at: datetime | None = None
    expires_at: datetime | None = None
    last_successful_refresh: datetime | None = None
    last_attempted_refresh: datetime | None = None
    last_error: str = ""
    failure_count: int = 0

    @property
    def is_stale(self) -> bool:
        return self.state == CacheState.STALE


@dataclass(frozen=True)
class CacheStatistics:
    total_records: int
    fresh_records: int
    stale_records: int
    failed_records: int


@dataclass(frozen=True)
class AiringScheduleCacheRecord:
    state: CacheState
    episodes: tuple[AniListAiringEpisode, ...] = ()
    retrieved_at: datetime | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True)
class RelationsCacheRecord:
    state: CacheState
    relations: tuple[AniListRelation, ...] = ()
    retrieved_at: datetime | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True)
class AiringCandidateEvent:
    event_type: AiringEventType
    media_id: int
    episode_number: int | None = None
    previous_airing_at: datetime | None = None
    new_airing_at: datetime | None = None
    details: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class FranchiseGraph:
    nodes: frozenset[int]
    edges: tuple[AniListRelation, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class FranchiseGroupSuggestion:
    group_id: str
    member_anilist_ids: tuple[int, ...]
    relation_evidence: tuple[AniListRelation, ...]
    suggested_main_title: str
    confidence: str
    manual_confirmation_state: str = "UNCONFIRMED"
    warnings: tuple[str, ...] = ()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_partial_date(value: Mapping[str, Any] | None) -> date | None:
    if not value or not value.get("year"):
        return None
    try:
        return date(int(value["year"]), int(value.get("month") or 1), int(value.get("day") or 1))
    except (TypeError, ValueError):
        return None


def parse_datetime_timestamp(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def parse_media_kind(value: Any) -> MediaKind:
    try:
        return MediaKind(str(value or "UNKNOWN"))
    except ValueError:
        return MediaKind.UNKNOWN


def parse_anilist_status(value: Any) -> AniListStatus:
    try:
        return AniListStatus(str(value or "UNKNOWN"))
    except ValueError:
        return AniListStatus.UNKNOWN


def parse_relation_type(value: Any) -> RelationType:
    normalized = str(value or "OTHER").replace("_", " ").strip().upper().replace(" ", "_")
    aliases = {"SIDE_STORY": RelationType.SIDE_STORY, "SPIN_OFF": RelationType.SPIN_OFF}
    if normalized in aliases:
        return aliases[normalized]
    try:
        return RelationType(normalized)
    except ValueError:
        return RelationType.OTHER


def parse_airing_episode(value: Mapping[str, Any] | None, media_id: int, now: datetime) -> AniListAiringEpisode | None:
    if not value or not value.get("episode") or not value.get("airingAt"):
        return None
    airing_at = parse_datetime_timestamp(value.get("airingAt"))
    if airing_at is None:
        return None
    return AniListAiringEpisode(
        media_id=media_id,
        episode_number=int(value["episode"]),
        airing_at=airing_at,
        time_until_airing=int(value["timeUntilAiring"]) if value.get("timeUntilAiring") is not None else None,
        has_aired=airing_at <= now,
        schedule_id=int(value["id"]) if value.get("id") is not None else None,
    )


def parse_relation(edge: Mapping[str, Any], source_id: int, retrieved_at: datetime) -> AniListRelation | None:
    node = edge.get("node") or {}
    target_id = node.get("id")
    if not target_id:
        return None
    titles = node.get("title") or {}
    title = titles.get("english") or titles.get("romaji") or titles.get("native") or ""
    return AniListRelation(
        source_anilist_id=source_id,
        target_anilist_id=int(target_id),
        relation_type=parse_relation_type(edge.get("relationType")),
        target_format=parse_media_kind(node.get("format")),
        target_status=parse_anilist_status(node.get("status")),
        target_title=str(title),
        retrieved_at=retrieved_at,
    )


def parse_media(payload: Mapping[str, Any], retrieved_at: datetime | None = None) -> AniListMedia:
    retrieved_at = retrieved_at or utc_now()
    if not isinstance(payload, Mapping) or not payload.get("id"):
        raise ValueError("AniList media payload is missing a valid ID.")
    media_id = int(payload["id"])
    titles = payload.get("title") or {}
    english = str(titles.get("english") or "")
    romaji = str(titles.get("romaji") or "")
    native = str(titles.get("native") or "")
    primary = english or romaji or native or f"AniList {media_id}"
    next_episode = parse_airing_episode(payload.get("nextAiringEpisode"), media_id, retrieved_at)
    edges = ((payload.get("relations") or {}).get("edges") or [])
    relations = tuple(item for edge in edges if (item := parse_relation(edge, media_id, retrieved_at)) is not None)
    cover = payload.get("coverImage") or {}
    return AniListMedia(
        anilist_id=media_id,
        mal_id=int(payload["idMal"]) if payload.get("idMal") is not None else None,
        title=AniListTitle(primary, english, romaji, native, tuple(str(item) for item in payload.get("synonyms") or [] if item)),
        media_format=parse_media_kind(payload.get("format")),
        status=parse_anilist_status(payload.get("status")),
        season=str(payload.get("season") or ""),
        season_year=int(payload["seasonYear"]) if payload.get("seasonYear") is not None else None,
        start_date=parse_partial_date(payload.get("startDate")),
        end_date=parse_partial_date(payload.get("endDate")),
        episode_count=int(payload["episodes"]) if payload.get("episodes") is not None else None,
        duration_minutes=int(payload["duration"]) if payload.get("duration") is not None else None,
        country_of_origin=str(payload.get("countryOfOrigin") or ""),
        source=str(payload.get("source") or ""),
        genres=tuple(str(item) for item in payload.get("genres") or []),
        average_score=int(payload["averageScore"]) if payload.get("averageScore") is not None else None,
        popularity=int(payload["popularity"]) if payload.get("popularity") is not None else None,
        cover_images=CoverImages(str(cover.get("extraLarge") or ""), str(cover.get("large") or ""), str(cover.get("medium") or ""), str(cover.get("color") or "")),
        banner_image_url=str(payload.get("bannerImage") or ""),
        site_url=str(payload.get("siteUrl") or ""),
        description=str(payload.get("description") or ""),
        is_adult=bool(payload.get("isAdult", False)),
        provider_updated_at=int(payload["updatedAt"]) if payload.get("updatedAt") is not None else None,
        next_airing_episode=next_episode,
        relations=relations,
    )


def media_to_payload(media: AniListMedia) -> dict[str, Any]:
    def date_value(item: date | None) -> dict[str, int | None] | None:
        return {"year": item.year, "month": item.month, "day": item.day} if item else None

    def airing_value(item: AniListAiringEpisode | None) -> dict[str, Any] | None:
        if item is None:
            return None
        return {
            "id": item.schedule_id,
            "episode": item.episode_number,
            "airingAt": int(item.airing_at.timestamp()),
            "timeUntilAiring": item.time_until_airing,
        }

    return {
        "id": media.anilist_id,
        "idMal": media.mal_id,
        "title": {"english": media.title.english, "romaji": media.title.romaji, "native": media.title.native},
        "synonyms": list(media.title.synonyms),
        "format": media.media_format.value,
        "status": media.status.value,
        "season": media.season or None,
        "seasonYear": media.season_year,
        "startDate": date_value(media.start_date),
        "endDate": date_value(media.end_date),
        "episodes": media.episode_count,
        "duration": media.duration_minutes,
        "countryOfOrigin": media.country_of_origin,
        "source": media.source,
        "genres": list(media.genres),
        "averageScore": media.average_score,
        "popularity": media.popularity,
        "coverImage": {
            "extraLarge": media.cover_images.extra_large,
            "large": media.cover_images.large,
            "medium": media.cover_images.medium,
            "color": media.cover_images.color,
        },
        "bannerImage": media.banner_image_url,
        "siteUrl": media.site_url,
        "description": media.description,
        "isAdult": media.is_adult,
        "updatedAt": media.provider_updated_at,
        "nextAiringEpisode": airing_value(media.next_airing_episode),
        "relations": {
            "edges": [
                {
                    "relationType": relation.relation_type.value,
                    "node": {
                        "id": relation.target_anilist_id,
                        "format": relation.target_format.value,
                        "status": relation.target_status.value,
                        "title": {"english": relation.target_title, "romaji": "", "native": ""},
                    },
                }
                for relation in media.relations if relation.target_anilist_id is not None
            ]
        },
    }
