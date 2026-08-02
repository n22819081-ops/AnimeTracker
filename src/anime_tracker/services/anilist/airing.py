from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from ...domain.enums import AniListStatus
from .errors import AniListErrorType, AniListServiceError
from .models import AiringCandidateEvent, AiringEventType, AniListAiringEpisode, parse_datetime_timestamp


def parse_airing_rows(rows: Iterable[Mapping[str, Any]], now: datetime) -> tuple[AniListAiringEpisode, ...]:
    episodes: list[AniListAiringEpisode] = []
    for row in rows:
        airing_at = parse_datetime_timestamp(row.get("airingAt"))
        if airing_at is None or not row.get("mediaId") or not row.get("episode"):
            continue
        episodes.append(AniListAiringEpisode(
            int(row["mediaId"]), int(row["episode"]), airing_at,
            int(row["timeUntilAiring"]) if row.get("timeUntilAiring") is not None else None,
            airing_at <= now,
            int(row["id"]) if row.get("id") is not None else None,
        ))
    return tuple(sorted(episodes, key=lambda item: (item.airing_at, item.media_id, item.episode_number)))


def compare_airing_snapshots(
    previous: Iterable[AniListAiringEpisode],
    current: Iterable[AniListAiringEpisode],
    *,
    previous_status: AniListStatus | None = None,
    current_status: AniListStatus | None = None,
    expected_episode_count: int | None = None,
) -> tuple[AiringCandidateEvent, ...]:
    old = {(item.media_id, item.episode_number): item for item in previous}
    new = {(item.media_id, item.episode_number): item for item in current}
    events: list[AiringCandidateEvent] = []
    for key, item in sorted(new.items()):
        prior = old.get(key)
        if item.has_aired and (prior is None or not prior.has_aired):
            events.append(AiringCandidateEvent(AiringEventType.NEW_EPISODE_AIRED, item.media_id, item.episode_number, prior.airing_at if prior else None, item.airing_at))
        elif not item.has_aired and prior is None:
            events.append(AiringCandidateEvent(AiringEventType.NEXT_EPISODE_SCHEDULED, item.media_id, item.episode_number, None, item.airing_at))
        if prior and prior.airing_at != item.airing_at:
            event_type = AiringEventType.EPISODE_DELAYED if item.airing_at > prior.airing_at else AiringEventType.AIRING_TIME_CHANGED
            events.append(AiringCandidateEvent(event_type, item.media_id, item.episode_number, prior.airing_at, item.airing_at))
    for key, item in sorted(old.items()):
        if key not in new and not item.has_aired:
            events.append(AiringCandidateEvent(AiringEventType.AIRING_SCHEDULE_REMOVED, item.media_id, item.episode_number, item.airing_at, None))

    media_ids = sorted({item.media_id for item in (*old.values(), *new.values())})
    media_id = media_ids[0] if len(media_ids) == 1 else 0
    if previous_status == AniListStatus.NOT_YET_RELEASED and current_status == AniListStatus.RELEASING:
        events.append(AiringCandidateEvent(AiringEventType.SEASON_STARTED_AIRING, media_id))
    if previous_status != AniListStatus.FINISHED and current_status == AniListStatus.FINISHED:
        final_aired = expected_episode_count is None or any(
            item.has_aired and item.episode_number >= expected_episode_count for item in new.values()
        )
        no_future = not any(not item.has_aired for item in new.values())
        details = (("final_expected_episode_aired", str(final_aired)), ("no_future_schedule", str(no_future)))
        events.append(AiringCandidateEvent(AiringEventType.SERIES_FINISHED_AIRING, media_id, details=details))
    return tuple(dict.fromkeys(events))


def finished_evidence_warnings(
    *,
    status: AniListStatus,
    end_date_reached: bool,
    final_expected_episode_aired: bool,
    future_schedule_exists: bool,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if status == AniListStatus.FINISHED and future_schedule_exists:
        warnings.append("AniList reports FINISHED but a future airing remains scheduled.")
    if status != AniListStatus.FINISHED and end_date_reached and final_expected_episode_aired and not future_schedule_exists:
        warnings.append("Airing evidence suggests completion while AniList status is not FINISHED.")
    return tuple(warnings)
