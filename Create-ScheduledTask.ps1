param(
    [string]$TaskName = "Anime Tracker Weekly Check",
    [ValidateSet("Daily", "Weekly")]
    [string]$Frequency = "Weekly",
    [ValidateSet("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")]
    [string]$DayOfWeek = "Sunday",
    [string]$Time = "10:00",
    [string]$UserId = "$env:USERDOMAIN\$env:USERNAME",
    [switch]$Enabled,
    [switch]$StartWhenAvailable
)

$ErrorActionPreference = "Stop"
$Root = "C:\AnimeTracker"
$Python = Join-Path $Root ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $Python)) {
    $Python = Join-Path $Root ".venv\Scripts\python.exe"
}

if (-not (Test-Path $Python)) {
    throw "Virtual environment not found under C:\AnimeTracker\.venv. Run C:\AnimeTracker\Install.ps1 first."
}

$Action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "-m anime_tracker.app --scheduled-check" `
    -WorkingDirectory $Root

if ($Frequency -eq "Daily") {
    $Trigger = New-ScheduledTaskTrigger -Daily -At $Time
} else {
    $Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DayOfWeek -At $Time
}

$Principal = New-ScheduledTaskPrincipal `
    -UserId $UserId `
    -LogonType Interactive `
    -RunLevel Limited

$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable:$StartWhenAvailable.IsPresent `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Force | Out-Null

if ($Enabled.IsPresent) {
    Enable-ScheduledTask -TaskName $TaskName | Out-Null
} else {
    Disable-ScheduledTask -TaskName $TaskName | Out-Null
}

$RegisteredTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$TaskInfo = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
if ($RegisteredTask.TaskName -ne $TaskName) {
    throw "Scheduled task registration verification failed."
}

Write-Host "Scheduled task '$TaskName' installed or updated. User=$UserId Frequency=$Frequency Day=$DayOfWeek Time=$Time Enabled=$($Enabled.IsPresent) StartWhenAvailable=$($StartWhenAvailable.IsPresent) NextRun=$($TaskInfo.NextRunTime)"
