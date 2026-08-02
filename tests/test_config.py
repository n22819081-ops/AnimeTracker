import tempfile
import unittest
from pathlib import Path

from anime_tracker.config import NotificationConfig, load_notification_config, masked_webhook, save_notification_config, save_shared_silent_setting


class ConfigTests(unittest.TestCase):
    def test_saved_webhook_is_masked_for_display(self):
        self.assertEqual(masked_webhook("https://discord.com/api/webhooks/example"), "Saved (hidden)")

    def test_notification_config_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notification_config.json"
            save_notification_config(
                NotificationConfig(
                    discord_webhook_url="https://discord.com/api/webhooks/example",
                    discord_enabled=True,
                    windows_enabled=False,
                    shared_discord_webhook_url="https://discord.com/api/webhooks/shared-example",
                    shared_announcements_enabled=True,
                ),
                path,
            )
            loaded = load_notification_config(path)
            self.assertTrue(loaded.discord_enabled)
            self.assertFalse(loaded.windows_enabled)
            self.assertEqual(loaded.discord_webhook_url, "https://discord.com/api/webhooks/example")
            self.assertEqual(loaded.shared_discord_webhook_url, "https://discord.com/api/webhooks/shared-example")
            self.assertTrue(loaded.shared_announcements_enabled)

    def test_shared_silent_checkbox_setting_is_saved_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notification_config.json"
            save_notification_config(NotificationConfig(shared_send_silently=True), path)

            saved = save_shared_silent_setting(False, path)
            reloaded = load_notification_config(path)

            self.assertFalse(saved.shared_send_silently)
            self.assertFalse(reloaded.shared_send_silently)


if __name__ == "__main__":
    unittest.main()
