param(
    [switch]$Enabled,
    [ValidateSet("Daily", "Weekly")][string]$Frequency = "Weekly",
    [ValidateSet("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")][string]$DayOfWeek = "Sunday",
    [string]$Time = "10:00",
    [switch]$StartWhenAvailable
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Pythonw = Join-Path $Root ".venv\Scripts\pythonw.exe"
$TaskName = "Anime Tracker Modern - Validation"
if (-not (Test-Path -LiteralPath $Pythonw)) { throw "Modern Python environment was not found." }

$Action = New-ScheduledTaskAction -Execute $Pythonw -Argument "-m anime_tracker.production.scheduled_command --profile `"$Root\production_profile`"" -WorkingDirectory $Root
if ($Frequency -eq "Weekly") { $Trigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek $DayOfWeek -At $Time }
else { $Trigger = New-ScheduledTaskTrigger -Daily -At $Time }
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable:$StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 4)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

# Registration is an explicit user action. This script never disables the legacy task.
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
if (-not $Enabled) { Disable-ScheduledTask -TaskName $TaskName | Out-Null }
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName,State
