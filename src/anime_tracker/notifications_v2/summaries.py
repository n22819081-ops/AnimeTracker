from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping

from .enums import ChannelPurpose, EventType, PrivacyLevel
from .deduplication import weekly_key
from .models import NotificationEvent, SummarySection


PRIVATE_SECTION_ORDER = (
    "Episodes aired this week", "Episodes missing from server", "Series that started airing",
    "Series that finished airing", "Movies newly available", "Titles newly complete on server",
    "Open review cases", "AniList refresh failures", "Upcoming next week",
)
SHARED_SECTION_ORDER = (
    "New episodes added", "Seasons completed", "Movies added", "New series available",
)


def week_bounds(moment: datetime) -> tuple[datetime, datetime]:
    if moment.tzinfo is None:
        raise ValueError("Weekly summary timestamps must be timezone-aware.")
    utc = moment.astimezone(timezone.utc)
    start = (utc - timedelta(days=utc.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=7)


def build_summary_sections(data: Mapping[str, Iterable[str]], channel: ChannelPurpose) -> tuple[SummarySection, ...]:
    order = SHARED_SECTION_ORDER if channel == ChannelPurpose.SHARED_ANNOUNCEMENT else PRIVATE_SECTION_ORDER
    return tuple(SummarySection(heading, tuple(str(line) for line in data.get(heading, ()) if str(line).strip())) for heading in order if any(str(line).strip() for line in data.get(heading, ())))


def render_sections(sections: Iterable[SummarySection]) -> str:
    return "\n\n".join(f"**{section.heading}**\n" + "\n".join(f"- {line}" for line in section.lines) for section in sections)


def weekly_summary_event(
    moment: datetime,
    channel: ChannelPurpose,
    data: Mapping[str, Iterable[str]],
    *,
    event_id: str,
) -> NotificationEvent:
    start, _ = week_bounds(moment)
    shared = channel == ChannelPurpose.SHARED_ANNOUNCEMENT
    sections = build_summary_sections(data, channel)
    return NotificationEvent(
        event_id,
        EventType.WEEKLY_SERVER_SUMMARY if shared else EventType.WEEKLY_AIRING_SUMMARY,
        moment.astimezone(timezone.utc),
        weekly_key(start.date(), channel, shared),
        payload={"summary": render_sections(sections), "week_start": start.date().isoformat()},
        privacy_level=PrivacyLevel.SHARED_SAFE if shared else PrivacyLevel.PRIVATE,
        created_at=moment.astimezone(timezone.utc),
    )


def split_summary_lines(lines: Iterable[str], max_length: int = 3500) -> tuple[str, ...]:
    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}".strip()
        if current and len(candidate) > max_length:
            chunks.append(current)
            current = line[:max_length]
        else:
            current = candidate
    if current:
        chunks.append(current)
    return tuple(chunks)
