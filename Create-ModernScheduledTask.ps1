param(
    [switch]$Enabled,
    [ValidateSet("Daily", "Weekly")][string]$Frequency = "Weekly",
    [ValidateSet("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")][string]$DayOfWeek = "Sunday",
    [string]$Time = "10:00",
    [switch]$StartWhenAvailable,
    [Parameter(Mandatory = $true)][string]$ExecutablePath,
    [Parameter(Mandatory = $true)][string]$ProfilePath
)

$ErrorActionPreference = "Stop"
$TaskName = "Anime Tracker Modern - Validation"
if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) { throw "Packaged Anime Tracker executable was not found." }
if (-not [System.IO.Path]::IsPathRooted($ProfilePath)) { throw "Profile path must be absolute." }

$WorkingDirectory = Split-Path -Parent $ExecutablePath
$Action = New-ScheduledTaskAction -Execute $ExecutablePath -Argument "--scheduled-check --profile `"$ProfilePath`"" -WorkingDirectory $WorkingDirectory
if ($Frequency -eq "Weekly") { $Trigger = New-ScheduledTaskTrigger -Weekly -WeeksInterval 1 -DaysOfWeek $DayOfWeek -At $Time }
else { $Trigger = New-ScheduledTaskTrigger -Daily -At $Time }
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable:$StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 4)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

# Registration is an explicit user action. This script never disables the legacy task.
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
if (-not $Enabled) { Disable-ScheduledTask -TaskName $TaskName | Out-Null }
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName,State
