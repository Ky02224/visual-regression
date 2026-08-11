param(
    [switch]$NoDev,
    [switch]$InstallAllBrowsers
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$venvDir = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$requirementsFile = if ($NoDev) { "requirements.txt" } else { "requirements-dev.txt" }
$browserTarget = if ($InstallAllBrowsers) { @() } else { @("chromium") }

Write-Host "Project root: $projectRoot"

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}
else {
    Write-Host "Virtual environment already exists."
}

Write-Host "Upgrading pip..."
& $venvPython -m pip install --upgrade pip

Write-Host "Installing Python dependencies from $requirementsFile ..."
& $venvPython -m pip install -r $requirementsFile

Write-Host "Installing Playwright browser binaries..."
if ($browserTarget.Count -gt 0) {
    & $venvPython -m playwright install @browserTarget
}
else {
    & $venvPython -m playwright install
}

# serve-dashboard falls back to building the frontend itself when dist/ is
# missing, but that fallback needs node_modules already installed -- on a
# machine that has never run npm here, it fails outright instead (confirmed
# by extracting a clean copy of this repo and starting the server: backend
# came up, but / returned 404 because dashboard_frontend/dist was never
# produced). Doing it here means the first `serve-dashboard` run just works.
Write-Host "Installing frontend dependencies and building dashboard_frontend..."
Push-Location (Join-Path $projectRoot "dashboard_frontend")
npm install
npm run build
Pop-Location

Write-Host ""
Write-Host "Setup completed."
Write-Host "Activate the environment with:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host ""
Write-Host "Then try one of these commands:"
Write-Host "  python -m pytest -q"
Write-Host "  python -m visual_regression.cli serve-dashboard --port 8130"
Write-Host "  python -m visual_regression.cli create-suite-baselines --suite suite.demo.yaml --overwrite"
