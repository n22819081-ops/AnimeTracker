import tempfile
import unittest
import os
import time
from datetime import datetime
from pathlib import Path

from anime_tracker.database import Database
from anime_tracker.scheduler import ScheduledCheckStats, compute_next_check, record_schedule_install, run_scheduled_check
from anime_tracker.task_scheduler import (
    build_elevated_scheduled_task_args,
    build_scheduled_task_args,
    build_verify_task_args,
    is_uac_cancellation,
    parse_task_verification,
    registration_error_message,
)


class SchedulerTests(unittest.TestCase):
    def test_scheduled_check_records_command_result_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            lock = Path(tmp) / "scheduled.lock"

            def fake_check():
                return ScheduledCheckStats(
                    result="Success",
                    titles_updated=4,
                    moved_on_server=2,
                    moved_ready=1,
                    changes=3,
                )

            stats = run_scheduled_check(db=db, check_func=fake_check, lock_path=lock)
            settings = db.get_settings()

            self.assertEqual(stats.result, "Success")
            self.assertEqual(settings["scheduled_titles_updated"], "4")
            self.assertEqual(settings["scheduled_moved_on_server"], "2")
            self.assertEqual(settings["scheduled_moved_ready"], "1")
            self.assertEqual(settings["scheduled_last_result"], "Success")
            self.assertTrue(settings["scheduled_last_check"])
            self.assertTrue(settings["scheduled_next_check"])
            self.assertFalse(lock.exists())

    def test_duplicate_scheduled_run_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            lock = Path(tmp) / "scheduled.lock"
            lock.write_text("already-running", encoding="utf-8")

            called = {"value": False}

            def fake_check():
                called["value"] = True
                return ScheduledCheckStats()

            stats = run_scheduled_check(db=db, check_func=fake_check, lock_path=lock)
            settings = db.get_settings()

            self.assertTrue(stats.skipped_duplicate)
            self.assertFalse(called["value"])
            self.assertEqual(settings["scheduled_last_result"], "Skipped: already running")

    def test_stale_scheduled_lock_is_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            lock = Path(tmp) / "scheduled.lock"
            lock.write_text("old-process", encoding="utf-8")
            stale = time.time() - (4 * 60 * 60)
            os.utime(lock, (stale, stale))

            stats = run_scheduled_check(db=db, check_func=lambda: ScheduledCheckStats(changes=1), lock_path=lock)

            self.assertEqual(stats.result, "Success")
            self.assertFalse(stats.skipped_duplicate)
            self.assertFalse(lock.exists())

    def test_default_weekly_next_check_is_sunday_10am(self):
        settings = {
            "schedule_frequency": "Weekly",
            "schedule_day": "Sunday",
            "schedule_time": "10:00",
        }
        next_check = compute_next_check(settings, now=datetime(2026, 7, 6, 9, 0))
        self.assertEqual(next_check, "2026-07-12T10:00")

    def test_task_install_record_refreshes_stale_next_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "tracker.db")
            db.set_settings({"scheduled_next_check": "2020-01-01T10:00"})

            next_check = record_schedule_install(db)
            settings = db.get_settings()

            self.assertEqual(settings["scheduled_next_check"], next_check)
            self.assertGreater(next_check, "2026-07-23T00:00")
            self.assertEqual(settings["scheduled_last_result"], "Task installed; awaiting scheduled run")

    def test_enabled_schedule_passes_enabled_switch_only(self):
        args = build_scheduled_task_args(
            Path(r"C:\AnimeTracker"),
            {
                "schedule_enabled": "true",
                "schedule_start_when_available": "true",
                "schedule_frequency": "Weekly",
                "schedule_day": "Sunday",
                "schedule_time": "10:00",
            },
        )
        self.assertIn("-Enabled", args)
        self.assertIn("-StartWhenAvailable", args)
        self.assertNotIn("$true", args)
        self.assertNotIn("True", args)
        self.assertIn("-UserId", args)

    def test_disabled_schedule_omits_enabled_switch(self):
        args = build_scheduled_task_args(
            Path(r"C:\AnimeTracker"),
            {
                "schedule_enabled": "false",
                "schedule_start_when_available": "false",
                "schedule_frequency": "Weekly",
                "schedule_day": "Sunday",
                "schedule_time": "10:00",
            },
        )
        self.assertNotIn("-Enabled", args)
        self.assertNotIn("-StartWhenAvailable", args)
        self.assertNotIn("$false", args)
        self.assertNotIn("False", args)

    def test_weekly_schedule_arguments(self):
        args = build_scheduled_task_args(
            Path(r"C:\AnimeTracker"),
            {
                "schedule_enabled": "true",
                "schedule_frequency": "Weekly",
                "schedule_day": "Sunday",
                "schedule_time": "10:00",
            },
        )
        self.assertEqual(args[args.index("-Frequency") + 1], "Weekly")
        self.assertEqual(args[args.index("-DayOfWeek") + 1], "Sunday")

    def test_daily_schedule_arguments(self):
        args = build_scheduled_task_args(
            Path(r"C:\AnimeTracker"),
            {
                "schedule_enabled": "true",
                "schedule_frequency": "Daily",
                "schedule_day": "Sunday",
                "schedule_time": "09:30",
            },
        )
        self.assertEqual(args[args.index("-Frequency") + 1], "Daily")
        self.assertEqual(args[args.index("-Time") + 1], "09:30")

    def test_script_registers_task_with_force_for_updates(self):
        script = Path("Create-ScheduledTask.ps1").read_text(encoding="utf-8")
        self.assertIn("Register-ScheduledTask", script)
        self.assertIn("-Force", script)
        self.assertIn("pythonw.exe", script)
        self.assertIn("Get-ScheduledTaskInfo", script)
        self.assertIn("-RestartCount 3", script)

    def test_runlevel_uses_limited_or_highest_only(self):
        script = Path("Create-ScheduledTask.ps1").read_text(encoding="utf-8")
        self.assertIn("-RunLevel Limited", script)
        self.assertNotIn("-RunLevel LeastPrivilege", script)

    def test_elevation_request_construction_uses_runas(self):
        args = build_elevated_scheduled_task_args(
            Path(r"C:\AnimeTracker"),
            {
                "schedule_enabled": "true",
                "schedule_start_when_available": "true",
                "schedule_frequency": "Weekly",
                "schedule_day": "Sunday",
                "schedule_time": "10:00",
            },
        )
        command = args[-1]
        self.assertIn("-Verb RunAs", command)
        self.assertIn("Start-Process", command)
        self.assertIn("-Enabled", command)
        self.assertIn("-StartWhenAvailable", command)
        self.assertNotIn("discord", command.lower())

    def test_uac_cancellation_is_detected(self):
        self.assertTrue(is_uac_cancellation(1223, ""))
        self.assertTrue(is_uac_cancellation(1, "The operation was canceled by the user."))

    def test_successful_task_verification_parse(self):
        args = build_verify_task_args()
        self.assertIn("Get-ScheduledTask", args[-1])
        info = parse_task_verification('{"TaskName":"Anime Tracker Weekly Check","Enabled":true,"NextRunTime":"7/19/2026 10:00:00 AM"}')
        self.assertEqual(info["task_name"], "Anime Tracker Weekly Check")
        self.assertTrue(info["enabled"])
        self.assertEqual(info["next_run_time"], "7/19/2026 10:00:00 AM")

    def test_failed_registration_error_reports_command_and_error(self):
        args = build_elevated_scheduled_task_args(
            Path(r"C:\AnimeTracker"),
            {
                "schedule_enabled": "false",
                "schedule_frequency": "Daily",
                "schedule_day": "Sunday",
                "schedule_time": "09:00",
            },
        )
        message = registration_error_message(args, "Access is denied.")
        self.assertIn("Command failed:", message)
        self.assertIn("Access is denied.", message)
        self.assertIn("Start-Process", message)

    def test_batch_launchers_are_present_and_use_project_runtime(self):
        run_script = Path("Run-AnimeTracker.bat").read_text(encoding="utf-8")
        weekly_script = Path("Install-Weekly-Task.bat").read_text(encoding="utf-8")
        check_script = Path("Run-Scheduled-Check-Now.bat").read_text(encoding="utf-8")
        self.assertIn(".venv\\Scripts\\pythonw.exe", run_script)
        self.assertIn("-Verb RunAs", weekly_script)
        self.assertIn("-DayOfWeek','Sunday'", weekly_script)
        self.assertIn("-UserId", weekly_script)
        self.assertIn("--record-schedule-install", weekly_script)
        self.assertIn("--scheduled-check", check_script)


if __name__ == "__main__":
    unittest.main()
