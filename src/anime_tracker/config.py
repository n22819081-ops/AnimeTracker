from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .constants import DATA_DIR

LOGGER = logging.getLogger(__name__)
CONFIG_PATH = DATA_DIR / "notification_config.json"


@dataclass
class NotificationConfig:
    discord_webhook_url: str = ""
    discord_enabled: bool = False
    windows_enabled: bool = True
    notify_airing_starts: bool = True
    notify_airing_finishes: bool = True
    notify_found_on_server: bool = True
    notify_errors: bool = True
    notify_release_date_changes: bool = True
    shared_discord_webhook_url: str = ""
    shared_announcements_enabled: bool = False
    shared_send_silently: bool = True
    shared_announce_additions: bool = True
    shared_announce_removals: bool = False

    @property
    def has_webhook(self) -> bool:
        return bool(self.discord_webhook_url.strip())

    @property
    def has_shared_webhook(self) -> bool:
        return bool(self.shared_discord_webhook_url.strip())


def load_notification_config(path: Path = CONFIG_PATH) -> NotificationConfig:
    if not path.exists():
        return NotificationConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        allowed = {field.name for field in NotificationConfig.__dataclass_fields__.values()}
        return NotificationConfig(**{key: value for key, value in data.items() if key in allowed})
    except Exception as exc:
        LOGGER.warning("Notification config could not be read: %s", exc)
        return NotificationConfig()


def save_notification_config(config: NotificationConfig, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError as exc:
        LOGGER.info("Could not tighten notification config permissions: %s", exc)


def save_shared_silent_setting(enabled: bool, path: Path = CONFIG_PATH) -> NotificationConfig:
    config = load_notification_config(path)
    config.shared_send_silently = bool(enabled)
    save_notification_config(config, path)
    return config


def masked_webhook(value: str) -> str:
    if not value:
        return "Not set"
    return "Saved (hidden)"
