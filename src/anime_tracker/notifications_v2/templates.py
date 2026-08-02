from __future__ import annotations

import string
from dataclasses import replace
from datetime import datetime, timezone
from typing import Mapping

from .enums import ChannelPurpose, EventType, MentionPolicy
from .models import NotificationEvent, NotificationMessage
from .privacy import ensure_privacy_safe


PRIVATE_DEFAULTS = {
    EventType.STARTED_AIRING,
    EventType.NEW_EPISODE_AIRED,
    EventType.SERIES_FINISHED_AIRING,
    EventType.COVERAGE_BECAME_COMPLETE,
    EventType.MISSING_AIRED_EPISODES,
    EventType.CONFIRMED_PATH_MISSING,
    EventType.REVIEW_REQUIRED,
    EventType.PROVIDER_REFRESH_PARTIAL_FAILURE,
    EventType.WEEKLY_AIRING_SUMMARY,
}
SHARED_DEFAULTS = {
    EventType.SHARED_EPISODES_AVAILABLE,
    EventType.SHARED_SEASON_COMPLETE,
    EventType.SHARED_SERIES_AVAILABLE,
    EventType.MOVIE_FOUND_ON_SERVER,
    EventType.WEEKLY_SERVER_SUMMARY,
}


class TemplateError(ValueError):
    pass


def render_restricted(template: str, values: Mapping[str, object]) -> str:
    formatter = string.Formatter()
    fields = [name for _, name, spec, conversion in formatter.parse(template) if name]
    if any("." in name or "[" in name or spec or conversion for name, _, spec, conversion in (
        (name, literal, spec, conversion)
        for literal, name, spec, conversion in formatter.parse(template) if name
    )):
        raise TemplateError("Only simple placeholders are allowed.")
    missing = [name for name in fields if name not in values]
    if missing:
        raise TemplateError(f"Missing template placeholder: {missing[0]}")
    return template.format_map({key: str(value) for key, value in values.items()})


def render_event(event: NotificationEvent, channel: ChannelPurpose, *, silent: bool = False) -> NotificationMessage:
    values = {key: value for key, value in event.payload.items()}
    title_name = str(values.get("title") or values.get("english_title") or values.get("romaji_title") or "Anime")
    episode = values.get("episode")
    mapping = str(values.get("mapping_label") or "")
    coverage = str(values.get("coverage") or "Unknown")
    missing = _episode_text(values.get("missing_episodes", ()))

    private = {
        EventType.NEW_EPISODE_AIRED: ("New Episode Aired", f"{title_name}\nEpisode {episode} has aired."),
        EventType.STARTED_AIRING: ("Series Started Airing", f"{title_name} has started airing."),
        EventType.SERIES_FINISHED_AIRING: ("Series Finished Airing", f"{title_name} has finished airing."),
        EventType.MISSING_AIRED_EPISODES: ("Missing Aired Episodes", f"{title_name} is missing {missing}."),
        EventType.COVERAGE_BECAME_COMPLETE: ("Found on Jellyfin", f"{title_name} is now fully available on the server."),
        EventType.SERVER_MAPPING_CHANGED: ("Server Mapping Changed", f"{title_name} now maps to {mapping}."),
        EventType.REVIEW_REQUIRED: ("Review Required", f"{title_name} needs a matching decision."),
        EventType.PROVIDER_REFRESH_PARTIAL_FAILURE: ("AniList Refresh Partially Failed", "Some titles could not be refreshed and will be retried."),
        EventType.WEEKLY_AIRING_SUMMARY: ("Weekly Anime Tracker Summary", str(values.get("summary") or "Weekly summary is ready.")),
    }
    shared = {
        EventType.SHARED_EPISODES_AVAILABLE: ("New Episodes Available", f"{title_name} now has {_episode_text(values.get('episodes', ()))} available on Jellyfin."),
        EventType.SHARED_SEASON_COMPLETE: ("Season Complete", f"{title_name} is now complete on Jellyfin."),
        EventType.SHARED_SERIES_AVAILABLE: ("New Anime Available", f"{title_name} is now available on Jellyfin."),
        EventType.MOVIE_FOUND_ON_SERVER: ("New Anime Movie Available", f"{title_name} is now available on Jellyfin."),
        EventType.WEEKLY_SERVER_SUMMARY: ("This Week on Jellyfin", str(values.get("summary") or "New anime is available.")),
    }
    templates = shared if channel == ChannelPurpose.SHARED_ANNOUNCEMENT else private
    if event.event_type not in templates:
        raise TemplateError(f"No {channel.value} template for {event.event_type.value}.")
    title, body = templates[event.event_type]
    fields = []
    if channel == ChannelPurpose.PRIVATE_TRACKER:
        for label, key in (
            ("Aired", "aired_at"), ("AniList status", "anilist_status"),
            ("Server coverage", "coverage"), ("Missing", "missing_episodes"),
            ("Tracker status", "tracker_status"), ("Mapping", "mapping_label"),
            ("Action", "required_action"),
        ):
            value = values.get(key)
            if value not in (None, "", (), []):
                fields.append((label, _episode_text(value) if key == "missing_episodes" else str(value)))
    message = NotificationMessage(
        f"message-{event.event_id}-{channel.value.casefold()}", channel, title, body,
        tuple(fields), str(values.get("cover_url") or ""), timestamp=event.event_timestamp,
        silent=silent if channel == ChannelPurpose.SHARED_ANNOUNCEMENT else False,
        mention_policy=MentionPolicy.NONE,
    )
    ensure_privacy_safe(message_to_dict(message))
    return message


def message_to_dict(message: NotificationMessage) -> dict:
    return {
        "message_id": message.message_id,
        "channel_purpose": message.channel_purpose.value,
        "title": message.title,
        "body": message.body,
        "fields": list(message.fields),
        "thumbnail_url": message.thumbnail_url,
        "footer": message.footer,
        "timestamp": (message.timestamp or datetime.now(timezone.utc)).isoformat(),
        "silent": message.silent,
        "mention_policy": message.mention_policy.value,
        "privacy_safe": message.privacy_safe,
        "template_version": message.template_version,
    }


def compact_messages(message: NotificationMessage) -> tuple[NotificationMessage, ...]:
    fields = tuple((name[:256], value[:1024]) for name, value in message.fields[:25])
    body = message.body[:4096]
    compact = replace(message, title=message.title[:256], body=body, fields=fields, footer=message.footer[:2048])
    if len(body) <= 2000:
        return (compact,)
    chunks = tuple(body[index:index + 1900] for index in range(0, len(body), 1900))
    return tuple(replace(compact, body=chunk, title=compact.title if index == 0 else f"{compact.title} (continued)", fields=fields if index == 0 else ()) for index, chunk in enumerate(chunks))


def _episode_text(values) -> str:
    if isinstance(values, (list, tuple, set, frozenset)):
        numbers = sorted({int(value) for value in values})
        if not numbers:
            return "episodes"
        ranges = []
        start = previous = numbers[0]
        for number in numbers[1:]:
            if number == previous + 1:
                previous = number
                continue
            ranges.append((start, previous))
            start = previous = number
        ranges.append((start, previous))
        rendered = [str(start) if start == end else f"{start}-{end}" for start, end in ranges]
        prefix = "Episode" if len(numbers) == 1 else "Episodes"
        return f"{prefix} {', '.join(rendered)}"
    return str(values)
