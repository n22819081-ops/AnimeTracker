@echo off
setlocal
for %%I in ("%~dp0..") do set "ROOT=%%~fI\"
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
if not "%RESULT%"=="0" echo Scheduled check failed. See Legacy Anime Tracker\logs\anime_tracker.log.
pause
exit /b %RESULT%
