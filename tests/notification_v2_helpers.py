from __future__ import annotations

from datetime import datetime, timezone

from anime_tracker.notifications_v2 import (
    ChannelPurpose, EventType, NotificationEvent, NotificationMessage, PrivacyLevel,
)


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def event(key="event-key", *, event_id="event-1", event_type=EventType.NEW_EPISODE_AIRED, payload=None):
    return NotificationEvent(
        event_id,event_type,NOW,key,anilist_id=100,
        payload=payload or {"title":"Example Anime","episode":4,"coverage":"3 of 4"},
        privacy_level=PrivacyLevel.PRIVATE,created_at=NOW,
    )


def message(channel=ChannelPurpose.PRIVATE_TRACKER, *, silent=False, body="Example Anime Episode 4 has aired."):
    return NotificationMessage(
        f"message-{channel.value}",channel,"New Episode Aired",body,
        (("Coverage","3 of 4"),),timestamp=NOW,silent=silent,
    )
