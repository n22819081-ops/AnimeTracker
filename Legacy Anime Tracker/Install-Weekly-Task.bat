@echo off
setlocal
set "SCRIPT=%~dp0Create-ScheduledTask.ps1"
for %%I in ("%~dp0..") do set "ROOT=%%~fI\"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -PassThru -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File','%SCRIPT%','-Frequency','Weekly','-DayOfWeek','Sunday','-Time','10:00','-UserId','%USERDOMAIN%\%USERNAME%','-Enabled','-StartWhenAvailable'); exit $p.ExitCode"
if errorlevel 1 (
    echo.
    echo Weekly task installation was canceled or failed.
    pause
    exit /b 1
)
if exist "%ROOT%.venv\Scripts\python.exe" (
    pushd "%ROOT%"
    "%ROOT%.venv\Scripts\python.exe" -m anime_tracker.app --record-schedule-install
    popd
)
echo.
echo Anime Tracker weekly task installed for Sunday at 10:00 AM.
pause
endlocal
