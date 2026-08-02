from __future__ import annotations

from typing import Mapping

from .credentials import legacy_reference


def adapt_legacy_notification_config(metadata: Mapping[str, object]) -> dict:
    """Adapt explicitly supplied intent without retaining any supplied secret value."""
    private_present = bool(metadata.get("discord_webhook_url") or metadata.get("private_webhook_present"))
    shared_present = bool(metadata.get("shared_webhook_url") or metadata.get("shared_webhook_present"))
    private_reference, _ = legacy_reference("private", private_present)
    shared_reference, _ = legacy_reference("shared", shared_present)
    return {
        "private": {
            "enabled": bool(metadata.get("discord_enabled", False)),
            "credential_reference": private_reference,
            "secret_present": private_present,
        },
        "shared": {
            "enabled": bool(metadata.get("shared_enabled", False)),
            "credential_reference": shared_reference,
            "secret_present": shared_present,
            "silent": bool(metadata.get("shared_silent", False)),
        },
        "windows": {"enabled": bool(metadata.get("windows_enabled", False))},
    }
