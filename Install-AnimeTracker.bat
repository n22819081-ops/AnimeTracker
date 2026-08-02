@echo off
setlocal
set "ROOT=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%Install.ps1"
if errorlevel 1 (
    echo.
    echo Anime Tracker installation failed.
    pause
    exit /b 1
)
echo.
echo Anime Tracker installation completed.
pause
endlocal
