@echo off
setlocal
set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo Anime Tracker is not installed yet. Run Install-AnimeTracker.bat first.
    pause
    exit /b 1
)
pushd "%ROOT%"
"%PYTHON%" -m anime_tracker.app --scheduled-check
set "RESULT=%ERRORLEVEL%"
popd
if not "%RESULT%"=="0" echo Scheduled check failed. See logs\anime_tracker.log.
pause
exit /b %RESULT%
