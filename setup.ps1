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

Write-Host ""
Write-Host "Setup completed."
Write-Host "Activate the environment with:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host ""
Write-Host "Then try one of these commands:"
Write-Host "  python -m pytest -q"
Write-Host "  python -m visual_regression.cli serve-dashboard --port 8130"
Write-Host "  python -m visual_regression.cli create-suite-baselines --suite suite.demo.yaml --overwrite"
