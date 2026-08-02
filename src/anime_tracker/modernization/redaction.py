from __future__ import annotations

import re
from typing import Any


WEBHOOK_PATTERN = re.compile(r"https://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/[^\s\"']+", re.IGNORECASE)
SECRET_KEYS = {"discord_webhook_url", "shared_discord_webhook_url", "webhook", "token", "password", "secret"}


def redact_text(value: str) -> str:
    return WEBHOOK_PATTERN.sub("<redacted-webhook>", value or "")


def redact_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "<redacted>" if any(secret in str(key).casefold() for secret in SECRET_KEYS) else redact_mapping(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_mapping(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
