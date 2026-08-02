from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from .credentials import CredentialStore
from .discord import DiscordDeliveryAdapter
from .enums import ChannelPurpose, DeliveryResultType, MentionPolicy
from .models import BatchResult, NotificationMessage
from .outbox import NotificationOutboxRepository


class NotificationDispatcher:
    def __init__(
        self,
        repository: NotificationOutboxRepository,
        credentials: CredentialStore,
        discord: DiscordDeliveryAdapter,
    ) -> None:
        self.repository = repository
        self.credentials = credentials
        self.discord = discord

    def dispatch(self, worker_id: str, now: datetime, *, limit: int = 100) -> BatchResult:
        claimed = self.repository.claim_batch(worker_id, now, limit=limit)
        delivered = retry = failed = canceled = 0
        for item in claimed:
            try:
                secret = self.credentials.retrieve_secret(item.credential_reference).reveal()
                message = _message(item.payload)
                result = self.discord.deliver(secret, message)
            except KeyError:
                from .models import DeliveryResult
                result = DeliveryResult(DeliveryResultType.PERMANENT_FAILURE, error_type="MissingCredential", error_summary="Credential reference is unavailable.")
            updated = self.repository.complete(item.outbox_id, worker_id, result, now)
            if updated.status.value == "DELIVERED":
                delivered += 1
            elif updated.status.value == "RETRY_WAIT":
                retry += 1
            elif updated.status.value == "CANCELED":
                canceled += 1
            else:
                failed += 1
        return BatchResult(len(claimed), delivered=delivered, retry_pending=retry, permanently_failed=failed, canceled=canceled)


def _message(payload: dict) -> NotificationMessage:
    return NotificationMessage(
        payload["message_id"],ChannelPurpose(payload["channel_purpose"]),payload["title"],payload["body"],
        tuple(tuple(field) for field in payload.get("fields", ())),payload.get("thumbnail_url", ""),payload.get("footer", "Anime Tracker"),
        datetime.fromisoformat(payload["timestamp"]) if payload.get("timestamp") else None,
        bool(payload.get("silent")),MentionPolicy(payload.get("mention_policy", "NONE")),bool(payload.get("privacy_safe", True)),int(payload.get("template_version", 1)),
    )
