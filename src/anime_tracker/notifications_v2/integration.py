from __future__ import annotations

from datetime import datetime, timezone

from .discord import DiscordDeliveryAdapter
from .enums import ChannelPurpose, DeliveryResultType
from .models import NotificationMessage


def run_optional_discord_check(
    *,
    enabled: bool,
    dedicated_test_webhook: str = "",
    adapter: DiscordDeliveryAdapter | None = None,
) -> dict:
    if not enabled:
        return {"ran":False,"result":"DISABLED"}
    if not dedicated_test_webhook.strip():
        raise ValueError("An explicitly supplied dedicated test webhook is required.")
    message=NotificationMessage(
        "milestone-6-manual-check",ChannelPurpose.PRIVATE_TRACKER,
        "Anime Tracker Milestone 6 Test","Explicit manual notification-v2 integration check.",
        timestamp=datetime.now(timezone.utc),
    )
    result=(adapter or DiscordDeliveryAdapter()).deliver(dedicated_test_webhook,message)
    return {
        "ran":True,
        "result":result.result.value,
        "http_status":result.http_status,
        "error_type":result.error_type,
        "successful":result.result==DeliveryResultType.DELIVERED,
    }
