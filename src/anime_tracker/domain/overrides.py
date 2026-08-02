from __future__ import annotations

from datetime import datetime
from typing import Iterable

from .enums import OverrideType, ServerPresence, TrackerWorkflowStatus
from .models import ManualOverride


def active_overrides(overrides: Iterable[ManualOverride], at: datetime | None = None) -> tuple[ManualOverride, ...]:
    return tuple(
        sorted(
            (
                item for item in overrides
                if item.active and item.superseded_at is None and (item.expires_at is None or at is None or item.expires_at > at)
            ),
            key=lambda item: (item.created_at, item.override_id),
        )
    )


def last_override(overrides: Iterable[ManualOverride], override_type: OverrideType) -> ManualOverride | None:
    matches = [item for item in overrides if item.override_type == override_type]
    return matches[-1] if matches else None


def parse_workflow_override(value: object) -> TrackerWorkflowStatus | None:
    try:
        return value if isinstance(value, TrackerWorkflowStatus) else TrackerWorkflowStatus(str(value))
    except ValueError:
        return None


def parse_presence_override(value: object) -> ServerPresence | None:
    try:
        return value if isinstance(value, ServerPresence) else ServerPresence(str(value))
    except ValueError:
        return None


def suppresses_automatic_matching(overrides: Iterable[ManualOverride], at: datetime | None = None) -> bool:
    active = active_overrides(overrides, at)
    item = last_override(active, OverrideType.SUPPRESS_AUTOMATIC_MATCHING)
    return item is not None and bool(item.value)
