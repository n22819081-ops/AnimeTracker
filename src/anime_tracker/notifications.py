from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from .constants import APP_NAME
from .config import NotificationConfig, load_notification_config

LOGGER = logging.getLogger(__name__)


class Notifier:
    def __init__(self, config: NotificationConfig | None = None) -> None:
        self.config = config or load_notification_config()

    def reload(self) -> None:
        self.config = load_notification_config()

    def notify(self, title: str, message: str) -> None:
        if self.config.windows_enabled:
            self._windows_toast(title, message)

    def send_anime_event(
        self,
        event_title: str,
        row: Any,
        previous_status: str,
        new_status: str,
        found_on_jellyfin: bool,
        event_type: str,
        cover_image_url: str | None = None,
        extra_fields: dict[str, str] | None = None,
    ) -> bool:
        content = f"{row['english_title']} changed: {previous_status} -> {new_status}"
        discord_sent = self._discord_embed(
            event_title=event_title,
            row=row,
            previous_status=previous_status,
            new_status=new_status,
            found_on_jellyfin=found_on_jellyfin,
            cover_image_url=cover_image_url or row["cover_image_url"],
            extra_fields=extra_fields,
        )
        if self.config.windows_enabled:
            self._windows_toast(APP_NAME, content)
        return discord_sent

    def send_test(self) -> bool:
        fake = {
            "english_title": "Anime Tracker Test",
            "romaji_title": "Anime Tracker Test",
            "total_episodes": "",
            "anilist_url": "https://anilist.co",
            "cover_image_url": "",
        }
        return self._discord_embed(
            event_title="Test Notification",
            row=fake,
            previous_status="Test",
            new_status="Discord Connected",
            found_on_jellyfin=False,
            cover_image_url="",
            extra_fields={"Result": "Discord webhook is configured."},
        )

    def send_scheduled_summary(self, stats) -> bool:
        if not self.config.discord_enabled or not self.config.discord_webhook_url.strip():
            return False
        embed = {
            "title": "Scheduled Anime Tracker Check",
            "color": 0x5865F2,
            "fields": [
                {"name": "Result", "value": stats.result or "Success", "inline": True},
                {"name": "Titles Updated", "value": str(stats.titles_updated), "inline": True},
                {"name": "Moved On Server", "value": str(stats.moved_on_server), "inline": True},
                {"name": "Moved Ready", "value": str(stats.moved_ready), "inline": True},
                {"name": "Changes", "value": str(stats.changes), "inline": True},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            response = requests.post(self.config.discord_webhook_url, json={"username": APP_NAME, "embeds": [embed]}, timeout=15)
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            LOGGER.warning("Discord scheduled summary failed without exposing webhook; error type: %s", type(exc).__name__)
            return False

    def _discord_embed(
        self,
        event_title: str,
        row: Any,
        previous_status: str,
        new_status: str,
        found_on_jellyfin: bool,
        cover_image_url: str,
        extra_fields: dict[str, str] | None = None,
    ) -> bool:
        if not self.config.discord_enabled or not self.config.discord_webhook_url.strip():
            return False
        fields = [
            {"name": "English Title", "value": str(row["english_title"] or "Unknown"), "inline": True},
            {"name": "Romaji Title", "value": str(row["romaji_title"] or "Unknown"), "inline": True},
            {"name": "Previous Status", "value": previous_status or "Unknown", "inline": True},
            {"name": "New Status", "value": new_status or "Unknown", "inline": True},
            {"name": "Episodes", "value": str(row["total_episodes"] or "Unknown"), "inline": True},
            {"name": "Found on Jellyfin", "value": "Yes" if found_on_jellyfin else "No", "inline": True},
            {"name": "AniList", "value": str(row["anilist_url"] or "Unavailable"), "inline": False},
        ]
        for name, value in (extra_fields or {}).items():
            fields.append({"name": name, "value": value or "Unknown", "inline": False})
        embed = {
            "title": event_title,
            "url": row["anilist_url"] or None,
            "color": 0x5865F2,
            "fields": fields,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if cover_image_url:
            embed["thumbnail"] = {"url": cover_image_url}
        payload = {"username": APP_NAME, "embeds": [embed]}
        try:
            response = requests.post(self.config.discord_webhook_url, json=payload, timeout=15)
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            LOGGER.warning("Discord notification failed without exposing webhook; error type: %s", type(exc).__name__)
            return False

    def _windows_toast(self, title: str, message: str) -> None:
        try:
            from winotify import Notification

            toast = Notification(app_id=APP_NAME, title=title, msg=message)
            toast.show()
        except Exception as exc:
            LOGGER.info("Notification fallback: %s - %s (%s)", title, message, exc)
