$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found. Run Install.ps1 first."
}

Set-Location -LiteralPath $projectRoot
$forward = @($args)
if ($forward -contains "--reset-profile") {
    throw "--reset-profile was removed. Use --test-profile --reset-test-profile. Production reset requires a verified backup and explicit migration tooling."
}
& $python -m anime_tracker.gui_qt.application @forward
