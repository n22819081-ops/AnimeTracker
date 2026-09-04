@echo off
setlocal
for %%I in ("%~dp0..") do set "ROOT=%%~fI\"
set "PYTHON=%ROOT%.venv\Scripts\pythonw.exe"
if not exist "%PYTHON%" set "PYTHON=%ROOT%.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo Anime Tracker is not installed yet. Run Install-AnimeTracker.bat first.
    pause
    exit /b 1
)
start "Anime Tracker" /D "%ROOT%" "%PYTHON%" -m anime_tracker.app %*
endlocal
