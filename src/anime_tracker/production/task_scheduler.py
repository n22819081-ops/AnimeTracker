from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from ..runtime import application_directory,packaged_resource


VALIDATION_TASK_NAME="Anime Tracker Modern - Validation"


def powershell_executable()->Path:
    return Path(os.environ.get("SystemRoot","C:\\Windows"))/"System32"/"WindowsPowerShell"/"v1.0"/"powershell.exe"


def build_install_args(profile_root:Path,settings:dict)->list[str]:
    executable=Path(sys.executable).resolve();script=packaged_resource("Create-ModernScheduledTask.ps1");powershell=powershell_executable()
    script_args=["-NoProfile","-ExecutionPolicy","Bypass","-File",str(script),"-Frequency",settings.get("schedule_frequency","Weekly"),"-DayOfWeek",settings.get("schedule_day","Sunday"),"-Time",settings.get("schedule_time","10:00"),"-ExecutablePath",str(executable),"-ProfilePath",str(Path(profile_root).resolve())]
    if settings.get("scheduled_checks_enabled"):script_args.append("-Enabled")
    if settings.get("run_when_missed",True):script_args.append("-StartWhenAvailable")
    arguments=",".join("'"+item.replace("'","''")+"'" for item in script_args)
    command=f"try {{ $p=Start-Process -FilePath '{str(powershell).replace("'","''")}' -Verb RunAs -Wait -PassThru -ArgumentList @({arguments}); exit $p.ExitCode }} catch {{ Write-Error $_.Exception.Message; exit 1223 }}"
    return [str(powershell),"-NoProfile","-ExecutionPolicy","Bypass","-Command",command]


def build_verify_args()->list[str]:
    command=f"$t=Get-ScheduledTask -TaskName '{VALIDATION_TASK_NAME}' -ErrorAction Stop;$i=Get-ScheduledTaskInfo -TaskName '{VALIDATION_TASK_NAME}';[pscustomobject]@{{TaskName=$t.TaskName;Enabled=($t.State -ne 'Disabled');NextRunTime=[string]$i.NextRunTime;LastResult=$i.LastTaskResult}}|ConvertTo-Json -Compress"
    return [str(powershell_executable()),"-NoProfile","-ExecutionPolicy","Bypass","-Command",command]


def install_validation_task(profile_root:Path,settings:dict,*,run=subprocess.run)->dict:
    if not getattr(sys,"frozen",False) and run is subprocess.run:return {"installed":False,"canceled":False,"message":"Validation-task installation requires the packaged Anime Tracker application."}
    result=run(build_install_args(profile_root,settings),cwd=application_directory(),capture_output=True,text=True,check=False)
    if result.returncode==1223: return {"installed":False,"canceled":True,"message":"Scheduled task installation was canceled."}
    if result.returncode!=0: return {"installed":False,"canceled":False,"message":(result.stderr or result.stdout or "Task registration failed.").strip()}
    verified=run(build_verify_args(),cwd=application_directory(),capture_output=True,text=True,check=False)
    if verified.returncode!=0:return {"installed":False,"canceled":False,"message":(verified.stderr or "Task verification failed.").strip()}
    return {"installed":True,"canceled":False,"task":json.loads(verified.stdout)}
