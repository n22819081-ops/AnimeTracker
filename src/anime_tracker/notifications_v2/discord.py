from __future__ import annotations

from threading import Event
from typing import Callable

import requests

from .enums import DeliveryResultType
from .models import DeliveryResult, NotificationMessage
from .privacy import safe_error_summary
from .retry import PERMANENT_HTTP_STATUSES, RETRYABLE_HTTP_STATUSES
from .templates import compact_messages


SILENT_MESSAGE_FLAG = 4096


class DiscordDeliveryAdapter:
    def __init__(self, *, post: Callable = requests.post, timeout: float = 15.0) -> None:
        self._post = post
        self.timeout = timeout

    def deliver(self, webhook_url: str, message: NotificationMessage, *, cancel: Event | None = None) -> DeliveryResult:
        if not webhook_url.strip():
            return DeliveryResult(
                DeliveryResultType.PERMANENT_FAILURE,
                retryable=False,
                error_type="INVALID_WEBHOOK",
                error_summary="Discord credential is empty.",
            )
        if cancel and cancel.is_set():
            return DeliveryResult(DeliveryResultType.CANCELED, error_type="Canceled")
        messages = compact_messages(message)
        try:
            for part in messages:
                if cancel and cancel.is_set():
                    return DeliveryResult(DeliveryResultType.CANCELED, error_type="Canceled")
                response = self._post(
                    webhook_url,
                    json=discord_payload(part),
                    timeout=self.timeout,
                    headers={"User-Agent": "AnimeTracker/0.8 notification-v2"},
                )
                status = int(response.status_code)
                if 200 <= status < 300:
                    continue
                retry_after = None
                if status == 429:
                    try:
                        retry_after = float(response.json().get("retry_after", 0))
                    except (TypeError, ValueError, AttributeError):
                        retry_after = None
                if status in RETRYABLE_HTTP_STATUSES:
                    return DeliveryResult(DeliveryResultType.RETRYABLE_FAILURE, status, True, f"HTTP_{status}", f"Discord returned HTTP {status}.", {"parts": len(messages)}, retry_after)
                error = "INVALID_WEBHOOK" if status in {401, 403, 404} else f"HTTP_{status}"
                return DeliveryResult(DeliveryResultType.PERMANENT_FAILURE, status, False, error, f"Discord returned HTTP {status}.")
            return DeliveryResult(DeliveryResultType.DELIVERED, 204, response_metadata={"parts": len(messages)})
        except (requests.Timeout, requests.ConnectionError) as exc:
            return DeliveryResult(DeliveryResultType.RETRYABLE_FAILURE, retryable=True, error_type=type(exc).__name__, error_summary=safe_error_summary(exc))
        except requests.RequestException as exc:
            return DeliveryResult(DeliveryResultType.PERMANENT_FAILURE, retryable=False, error_type=type(exc).__name__, error_summary=safe_error_summary(exc))


def discord_payload(message: NotificationMessage) -> dict:
    embed = {
        "title": message.title[:256],
        "description": message.body[:4096],
        "fields": [{"name": name[:256], "value": value[:1024], "inline": False} for name, value in message.fields[:25]],
        "footer": {"text": message.footer[:2048]},
        "timestamp": message.timestamp.isoformat() if message.timestamp else None,
    }
    if message.thumbnail_url:
        embed["thumbnail"] = {"url": message.thumbnail_url}
    payload = {"username": "Anime Tracker", "embeds": [embed], "allowed_mentions": {"parse": []}}
    if message.silent:
        payload["flags"] = SILENT_MESSAGE_FLAG
    return payload
