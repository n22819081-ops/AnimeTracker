from __future__ import annotations

import hashlib
from datetime import date, datetime

from .enums import ChannelPurpose, EventType


def stable_key(event_type: EventType, *parts: object) -> str:
    raw = "|".join((event_type.value, *(canonical_part(part) for part in parts)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def channel_key(event_key: str, channel: ChannelPurpose) -> str:
    return hashlib.sha256(f"{channel.value}|{event_key}".encode("utf-8")).hexdigest()


def episode_key(anilist_id: int, episode: int, airing_time: datetime) -> str:
    return stable_key(EventType.NEW_EPISODE_AIRED, anilist_id, episode, airing_time)


def coverage_key(anilist_id: int, mapping_id: str, snapshot_id: str, complete: bool) -> str:
    event = EventType.COVERAGE_BECAME_COMPLETE if complete else EventType.COVERAGE_BECAME_PARTIAL
    return stable_key(event, anilist_id, mapping_id, snapshot_id)


def weekly_key(week_start: date, channel: ChannelPurpose, shared: bool = False) -> str:
    event = EventType.WEEKLY_SERVER_SUMMARY if shared else EventType.WEEKLY_AIRING_SUMMARY
    return stable_key(event, week_start.isoformat(), channel.value)


def canonical_part(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()
