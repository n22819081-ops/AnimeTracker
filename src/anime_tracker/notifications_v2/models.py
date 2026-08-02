from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from .enums import (
    BatchHealth, ChannelPurpose, DeliveryResultType, EventType, MentionPolicy,
    OutboxStatus, PrivacyLevel, Severity,
)


@dataclass(frozen=True)
class NotificationEvent:
    event_id: str
    event_type: EventType
    event_timestamp: datetime
    deduplication_key: str
    anilist_id: int | None = None
    franchise_id: str = ""
    source_transition_id: str = ""
    previous_state: str = ""
    new_state: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    severity: Severity = Severity.INFO
    privacy_level: PrivacyLevel = PrivacyLevel.PRIVATE
    correlation_id: str = ""
    created_at: datetime | None = None


@dataclass(frozen=True)
class NotificationMessage:
    message_id: str
    channel_purpose: ChannelPurpose
    title: str
    body: str
    fields: tuple[tuple[str, str], ...] = ()
    thumbnail_url: str = ""
    footer: str = "Anime Tracker"
    timestamp: datetime | None = None
    silent: bool = False
    mention_policy: MentionPolicy = MentionPolicy.NONE
    privacy_safe: bool = True
    template_version: int = 1


@dataclass(frozen=True)
class OutboxItem:
    outbox_id: str
    event_id: str
    channel_purpose: ChannelPurpose
    credential_reference: str
    payload: Mapping[str, Any]
    status: OutboxStatus
    attempt_count: int
    next_attempt_at: datetime | None
    claimed_by: str
    claim_expires_at: datetime | None
    created_at: datetime
    updated_at: datetime
    last_error_type: str = ""
    last_error_message: str = ""
    delivered_at: datetime | None = None
    deduplication_key: str = ""


@dataclass(frozen=True)
class DeliveryResult:
    result: DeliveryResultType
    http_status: int | None = None
    retryable: bool = False
    error_type: str = ""
    error_summary: str = ""
    response_metadata: Mapping[str, Any] = field(default_factory=dict)
    retry_after_seconds: float | None = None


@dataclass(frozen=True)
class BatchResult:
    total_events: int = 0
    enqueued: int = 0
    suppressed: int = 0
    delivered: int = 0
    retry_pending: int = 0
    permanently_failed: int = 0
    canceled: int = 0

    @property
    def health(self) -> BatchHealth:
        if self.total_events == 0:
            return BatchHealth.NO_WORK
        failures = self.retry_pending + self.permanently_failed + self.canceled
        if failures and self.delivered:
            return BatchHealth.PARTIAL_SUCCESS
        if failures:
            return BatchHealth.FAILED
        return BatchHealth.SUCCESS


@dataclass(frozen=True)
class SummarySection:
    heading: str
    lines: tuple[str, ...]
