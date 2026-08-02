from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from anime_tracker.domain.enums import AniListStatus, MediaKind, ServerPresence
from anime_tracker.domain.models import (
    AniListMediaIdentity,
    MediaTitle,
    ServerPresenceState,
    StatusDecisionInput,
)

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)


def identity(
    *,
    anilist_id: int = 1,
    status: AniListStatus = AniListStatus.FINISHED,
    kind: MediaKind = MediaKind.TV,
    expected: int | None = 12,
) -> AniListMediaIdentity:
    return AniListMediaIdentity(
        anilist_id,
        MediaTitle("Example", "Example Romaji", "Example Native", ("Example Alt",)),
        kind,
        status,
        expected_episodes=expected,
    )


def decision_input(
    *,
    media: AniListMediaIdentity | None = None,
    presence: ServerPresence = ServerPresence.NOT_FOUND,
    **changes: object,
) -> StatusDecisionInput:
    base = StatusDecisionInput(media or identity(), ServerPresenceState(presence))
    return replace(base, **changes)
