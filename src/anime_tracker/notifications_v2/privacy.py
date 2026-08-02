from __future__ import annotations

import json
import re
from typing import Any, Mapping


WEBHOOK = re.compile(r"https?://(?:canary\.|ptb\.)?discord(?:app)?\.com/api/webhooks/[^\s\"']+", re.I)
WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:\\[^\r\n,;]+")
TOKEN = re.compile(r"(?i)\b(?:token|api[_ -]?key|authorization|password)\b\s*[:=]\s*[^\s,;]+")
STACK = re.compile(r"(?is)traceback \(most recent call last\):.*")


class PrivacyViolation(ValueError):
    pass


def redact_text(value: str) -> str:
    value = STACK.sub("[REDACTED_STACK_TRACE]", value)
    value = WEBHOOK.sub("[REDACTED_WEBHOOK]", value)
    value = WINDOWS_PATH.sub("[REDACTED_PATH]", value)
    value = TOKEN.sub("[REDACTED_SECRET]", value)
    return value


def sanitize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return _sanitize(dict(payload))


def ensure_privacy_safe(payload: Mapping[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    sanitized = redact_text(serialized)
    if sanitized != serialized:
        raise PrivacyViolation("Notification payload contains sensitive local or credential data.")


def safe_error_summary(error: BaseException | str) -> str:
    text = str(error) if isinstance(error, BaseException) else error
    first_line = text.splitlines()[0] if text.splitlines() else ""
    return redact_text(first_line)[:300]


def _sanitize(value):
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items() if str(key).casefold() not in {"headers", "webhook_url", "token", "api_key"}}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    return value
