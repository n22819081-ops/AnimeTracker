$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found. Run Install.ps1 first."
}

Set-Location -LiteralPath $projectRoot
& $python -m anime_tracker.gui_qt.application @args
