param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

function Find-NativePython {
    $Candidates = @()
    $LocalPythonRoot = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "Programs\Python"
    if (Test-Path -LiteralPath $LocalPythonRoot -PathType Container) {
        $Candidates += Get-ChildItem -LiteralPath $LocalPythonRoot -Directory -Filter "Python*" |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName "python.exe" }
    }

    $PathPython = Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue
    if ($PathPython) {
        $Candidates += $PathPython.Source
    }

    $Seen = @{}
    foreach ($Candidate in $Candidates) {
        if (-not $Candidate -or $Seen.ContainsKey($Candidate)) { continue }
        $Seen[$Candidate] = $true
        if ($Candidate -match '(?i)\\(msys\d*|cygwin\d*|mingw\d*)\\') { continue }
        if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { continue }

        & $Candidate -c "import sys; raise SystemExit(0 if sys.implementation.name == 'cpython' and sys.version_info >= (3, 10) else 1)"
        if ($LASTEXITCODE -eq 0) { return $Candidate }
    }

    throw "A compatible native CPython 3.10+ installation was not found. Install Python from python.org, then run this installer again."
}

if (-not (Test-Path $Python)) {
    $BasePython = Find-NativePython
    & $BasePython -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "Python could not create the Anime Tracker virtual environment." }
}

# Keep child-process interpreter lookup inside this project without changing Windows PATH.
$env:Path = "$(Join-Path $Venv 'Scripts');$env:Path"
& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $Root "requirements.txt")
& $Python -m pip install -e $Root

if (-not $SkipTests) {
    & $Python -m pytest
}

Write-Host "Anime Tracker installed. Run .\Run-AnimeTracker.ps1 to start."
