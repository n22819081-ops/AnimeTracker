from __future__ import annotations

import json
import subprocess
from pathlib import Path


VALIDATION_TASK_NAME="Anime Tracker Modern - Validation"


def build_install_args(project_root:Path,settings:dict)->list[str]:
    script=project_root/"Create-ModernScheduledTask.ps1";script_args=["-NoProfile","-ExecutionPolicy","Bypass","-File",str(script),"-Frequency",settings.get("schedule_frequency","Weekly"),"-DayOfWeek",settings.get("schedule_day","Sunday"),"-Time",settings.get("schedule_time","10:00")]
    if settings.get("scheduled_checks_enabled"):script_args.append("-Enabled")
    if settings.get("run_when_missed",True):script_args.append("-StartWhenAvailable")
    arguments=",".join("'"+item.replace("'","''")+"'" for item in script_args)
    command=f"try {{ $p=Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -PassThru -ArgumentList @({arguments}); exit $p.ExitCode }} catch {{ Write-Error $_.Exception.Message; exit 1223 }}"
    return ["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-Command",command]


def build_verify_args()->list[str]:
    command=f"$t=Get-ScheduledTask -TaskName '{VALIDATION_TASK_NAME}' -ErrorAction Stop;$i=Get-ScheduledTaskInfo -TaskName '{VALIDATION_TASK_NAME}';[pscustomobject]@{{TaskName=$t.TaskName;Enabled=($t.State -ne 'Disabled');NextRunTime=[string]$i.NextRunTime;LastResult=$i.LastTaskResult}}|ConvertTo-Json -Compress"
    return ["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-Command",command]


def install_validation_task(project_root:Path,settings:dict,*,run=subprocess.run)->dict:
    result=run(build_install_args(project_root,settings),cwd=project_root,capture_output=True,text=True,check=False)
    if result.returncode==1223: return {"installed":False,"canceled":True,"message":"Scheduled task installation was canceled."}
    if result.returncode!=0: return {"installed":False,"canceled":False,"message":(result.stderr or result.stdout or "Task registration failed.").strip()}
    verified=run(build_verify_args(),cwd=project_root,capture_output=True,text=True,check=False)
    if verified.returncode!=0:return {"installed":False,"canceled":False,"message":(verified.stderr or "Task verification failed.").strip()}
    return {"installed":True,"canceled":False,"task":json.loads(verified.stdout)}
