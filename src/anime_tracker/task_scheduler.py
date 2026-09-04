from __future__ import annotations

from pathlib import Path
import json
import os


TASK_NAME = "Anime Tracker Weekly Check"


def build_scheduled_task_args(project_root: Path, settings: dict[str, str], executable: str = "powershell") -> list[str]:
    script = project_root / "Legacy Anime Tracker" / "Create-ScheduledTask.ps1"
    args = [
        executable,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-Frequency",
        settings.get("schedule_frequency", "Weekly"),
        "-DayOfWeek",
        settings.get("schedule_day", "Sunday"),
        "-Time",
        settings.get("schedule_time", "10:00"),
        "-UserId",
        current_windows_user(),
    ]
    if settings.get("schedule_enabled", "false") == "true":
        args.append("-Enabled")
    if settings.get("schedule_start_when_available", "true") == "true":
        args.append("-StartWhenAvailable")
    return args


def build_script_arguments(project_root: Path, settings: dict[str, str]) -> list[str]:
    script = project_root / "Legacy Anime Tracker" / "Create-ScheduledTask.ps1"
    args = [
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-Frequency",
        settings.get("schedule_frequency", "Weekly"),
        "-DayOfWeek",
        settings.get("schedule_day", "Sunday"),
        "-Time",
        settings.get("schedule_time", "10:00"),
        "-UserId",
        current_windows_user(),
    ]
    if settings.get("schedule_enabled", "false") == "true":
        args.append("-Enabled")
    if settings.get("schedule_start_when_available", "true") == "true":
        args.append("-StartWhenAvailable")
    return args


def build_elevated_scheduled_task_args(project_root: Path, settings: dict[str, str], executable: str = "powershell") -> list[str]:
    script_args = build_script_arguments(project_root, settings)
    argument_list = ",".join(ps_single_quote(arg) for arg in script_args)
    command = (
        "try { "
        f"$p = Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -PassThru -ArgumentList @({argument_list}); "
        "exit $p.ExitCode "
        "} catch { "
        "Write-Error $_.Exception.Message; exit 1223 "
        "}"
    )
    return [executable, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]


def build_verify_task_args(task_name: str = TASK_NAME, executable: str = "powershell") -> list[str]:
    task = ps_single_quote(task_name)
    command = (
        f"$task = Get-ScheduledTask -TaskName {task} -ErrorAction Stop; "
        f"$info = Get-ScheduledTaskInfo -TaskName {task} -ErrorAction Stop; "
        "[pscustomobject]@{"
        "TaskName=$task.TaskName;"
        "Enabled=($task.State -ne 'Disabled');"
        "NextRunTime=([string]$info.NextRunTime)"
        "} | ConvertTo-Json -Compress"
    )
    return [executable, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]


def parse_task_verification(output: str) -> dict[str, str | bool]:
    data = json.loads(output.strip())
    return {
        "task_name": data.get("TaskName", ""),
        "enabled": bool(data.get("Enabled")),
        "next_run_time": data.get("NextRunTime", ""),
    }


def registration_error_message(args: list[str], stderr: str, stdout: str = "") -> str:
    details = stderr.strip() or stdout.strip() or "Task Scheduler command failed."
    return f"Command failed:\n{format_command_for_error(args)}\n\n{details}"


def is_uac_cancellation(returncode: int, stderr: str, stdout: str = "") -> bool:
    text = f"{stderr}\n{stdout}".lower()
    return returncode == 1223 or "canceled by the user" in text or "cancelled by the user" in text or "operation was canceled" in text


def format_command_for_error(args: list[str]) -> str:
    return " ".join(quote_arg(arg) for arg in args)


def quote_arg(arg: str) -> str:
    if not arg or any(char.isspace() for char in arg):
        return f'"{arg}"'
    return arg


def ps_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def current_windows_user() -> str:
    username = os.environ.get("USERNAME", "")
    domain = os.environ.get("USERDOMAIN", "")
    return f"{domain}\\{username}" if domain and username else username
