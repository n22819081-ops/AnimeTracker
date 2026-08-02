from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .constants import DATA_DIR
from .database import Database

LOGGER = logging.getLogger(__name__)
LOCK_PATH = DATA_DIR / "scheduled_check.lock"


@dataclass
class ScheduledCheckStats:
    result: str = "Success"
    titles_updated: int = 0
    moved_on_server: int = 0
    moved_ready: int = 0
    changes: int = 0
    skipped_duplicate: bool = False
    error: str = ""

    def as_settings(self, next_check: str) -> dict[str, str]:
        return {
            "scheduled_last_check": datetime.now().isoformat(timespec="seconds"),
            "scheduled_next_check": next_check,
            "scheduled_last_result": self.result if not self.error else f"Failed: {self.error}",
            "scheduled_titles_updated": str(self.titles_updated),
            "scheduled_moved_on_server": str(self.moved_on_server),
            "scheduled_moved_ready": str(self.moved_ready),
        }


class DuplicateRunError(RuntimeError):
    pass


def record_schedule_install(db: Database | None = None) -> str:
    database = db or Database()
    settings = database.get_settings()
    next_check = compute_next_check(settings)
    database.set_settings(
        {
            "scheduled_next_check": next_check,
            "scheduled_last_result": "Task installed; awaiting scheduled run",
        }
    )
    LOGGER.info("Scheduled task installation recorded; next_check=%s", next_check)
    return next_check


class ScheduleLock:
    def __init__(self, path: Path = LOCK_PATH) -> None:
        self.path = path
        self.fd: int | None = None

    def __enter__(self) -> "ScheduleLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            age = datetime.now().timestamp() - self.path.stat().st_mtime
            if age > 3 * 60 * 60:
                LOGGER.warning("Removing stale scheduled-check lock older than three hours")
                self.path.unlink(missing_ok=True)
        try:
            self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self.fd, str(os.getpid()).encode("ascii"))
        except FileExistsError as exc:
            raise DuplicateRunError("A scheduled check is already running.") from exc
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def run_scheduled_check(
    db: Database | None = None,
    check_func: Callable[[], ScheduledCheckStats | dict | None] | None = None,
    lock_path: Path = LOCK_PATH,
) -> ScheduledCheckStats:
    database = db or Database()
    try:
        with ScheduleLock(lock_path):
            LOGGER.info("Scheduled check started")
            raw_stats = check_func() if check_func else ScheduledCheckStats()
            stats = coerce_stats(raw_stats)
            stats.result = stats.result or "Success"
            settings = database.get_settings()
            next_check = compute_next_check(settings)
            database.set_settings(stats.as_settings(next_check))
            LOGGER.info(
                "Scheduled check complete: titles_updated=%s moved_on_server=%s moved_ready=%s changes=%s",
                stats.titles_updated,
                stats.moved_on_server,
                stats.moved_ready,
                stats.changes,
            )
            return stats
    except DuplicateRunError:
        stats = ScheduledCheckStats(result="Skipped: already running", skipped_duplicate=True)
        database.set_settings(stats.as_settings(compute_next_check(database.get_settings())))
        LOGGER.info("Scheduled check skipped because another copy is running")
        return stats
    except Exception as exc:
        stats = ScheduledCheckStats(result="Failed", error=type(exc).__name__)
        database.set_settings(stats.as_settings(compute_next_check(database.get_settings())))
        LOGGER.exception("Scheduled check failed")
        return stats


def coerce_stats(value) -> ScheduledCheckStats:
    if isinstance(value, ScheduledCheckStats):
        return value
    if isinstance(value, dict):
        return ScheduledCheckStats(
            result=value.get("result", "Success"),
            titles_updated=int(value.get("titles_updated", 0)),
            moved_on_server=int(value.get("moved_on_server", 0)),
            moved_ready=int(value.get("moved_ready", 0)),
            changes=int(value.get("changes", 0)),
        )
    return ScheduledCheckStats()


def compute_next_check(settings: dict[str, str], now: datetime | None = None) -> str:
    current = now or datetime.now()
    frequency = settings.get("schedule_frequency", "Weekly")
    time_text = settings.get("schedule_time", "10:00")
    hour, minute = parse_time(time_text)
    candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if frequency == "Daily":
        if candidate <= current:
            candidate += timedelta(days=1)
        return candidate.isoformat(timespec="minutes")
    day_name = settings.get("schedule_day", "Sunday")
    target_weekday = weekday_number(day_name)
    days_ahead = (target_weekday - current.weekday()) % 7
    candidate += timedelta(days=days_ahead)
    if candidate <= current:
        candidate += timedelta(days=7)
    return candidate.isoformat(timespec="minutes")


def parse_time(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.strip().split(":", 1)
        hour = max(0, min(23, int(hour_text)))
        minute = max(0, min(59, int(minute_text)))
        return hour, minute
    except Exception:
        return 10, 0


def weekday_number(day_name: str) -> int:
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return days.index(day_name) if day_name in days else 6
