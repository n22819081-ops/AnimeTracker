import unittest

from anime_tracker.ui_layout import MAIN_TOOLBAR_ACTIONS, MAINTENANCE_ACTIONS


class UiLayoutTests(unittest.TestCase):
    def test_maintenance_actions_are_not_on_main_toolbar(self):
        labels = [label for label, _action in MAIN_TOOLBAR_ACTIONS]

        self.assertNotIn("Export CSV", labels)
        self.assertNotIn("Send Test Notification", labels)
        self.assertNotIn("Install or Update Scheduled Task", labels)
        self.assertNotIn("Run Scheduled Check Now", labels)

    def test_settings_maintenance_actions_use_existing_handlers(self):
        self.assertEqual(
            MAINTENANCE_ACTIONS,
            [
                ("Export Tracker CSV", "export_csv"),
                ("Send Test Notification", "send_test_notification"),
                ("Install or Update Scheduled Task", "install_or_update_scheduled_task"),
                ("Run Scheduled Check Now", "run_scheduled_check_now_threaded"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
