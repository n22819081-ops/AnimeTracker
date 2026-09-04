$ErrorActionPreference = "Stop"
$LegacyRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $LegacyRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Virtual environment not found. Run .\Install.ps1 first."
}

Set-Location -LiteralPath $Root
& $Python -m anime_tracker.app @args
