@echo off
setlocal
for %%I in ("%~dp0..") do set "ROOT=%%~fI\"
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
