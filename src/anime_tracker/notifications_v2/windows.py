from __future__ import annotations

from typing import Callable

from .models import DeliveryResult, NotificationMessage
from .enums import DeliveryResultType
from .privacy import ensure_privacy_safe, safe_error_summary
from .templates import message_to_dict


class WindowsNotificationAdapter:
    def __init__(self, *, enabled: bool = False, sender: Callable | None = None) -> None:
        self.enabled = enabled
        self._sender = sender or _default_sender

    def deliver(self, message: NotificationMessage) -> DeliveryResult:
        if not self.enabled:
            return DeliveryResult(DeliveryResultType.CANCELED, error_type="Disabled")
        try:
            ensure_privacy_safe(message_to_dict(message))
            self._sender(message.title, message.body)
            return DeliveryResult(DeliveryResultType.DELIVERED)
        except Exception as exc:
            return DeliveryResult(DeliveryResultType.PERMANENT_FAILURE, error_type=type(exc).__name__, error_summary=safe_error_summary(exc))


def _default_sender(title: str, body: str) -> None:
    from winotify import Notification

    Notification(app_id="Anime Tracker", title=title, msg=body).show()
