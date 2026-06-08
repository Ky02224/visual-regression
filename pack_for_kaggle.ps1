# pack_for_kaggle.ps1 - Pack only code files, exclude large folders
$root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$output = Join-Path ([Environment]::GetFolderPath("Desktop")) "FYP_VISUAL_colab.zip"

$exclude = @(
    "$root\scratch",
    "$root\.venv",
    "$root\.tmp_figma_review",
    "$root\.tmp_ai_studio_review",
    "$root\dashboard_frontend\node_modules",
    "$root\.visual-regression\models",
    "$root\.visual-regression\tmp"
)

Write-Host "Packing project (excluding large folders)..." -ForegroundColor Cyan

if (Test-Path $output) { Remove-Item $output -Force }

Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open($output, 'Create')

$items = Get-ChildItem -Path $root -Recurse -File -ErrorAction SilentlyContinue | Where-Object {
    $path = $_.FullName
    $skip = $false
    foreach ($ex in $exclude) {
        if ($path.StartsWith($ex)) { $skip = $true; break }
    }
    if ($_.Name -match '__pycache__|\.pyc$|\.pyo$|\.pyd$') { $skip = $true }
    -not $skip
}

$count = 0
foreach ($file in $items) {
    $relative = $file.FullName.Substring($root.Length + 1).Replace('\', '/')
    try {
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $zip, $file.FullName, $relative,
            [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
        $count++
        if ($count % 100 -eq 0) { Write-Host "  $count files packed..." }
    } catch {
        Write-Host "  Skipped: $relative"
    }
}

$zip.Dispose()

$sizeMB = [math]::Round((Get-Item $output).Length / 1MB, 1)
Write-Host ""
Write-Host "Done! $count files, $sizeMB MB" -ForegroundColor Green
Write-Host "Saved to: $output"
Write-Host ""
Write-Host "Next: Upload FYP_VISUAL_colab.zip to Kaggle Dataset" -ForegroundColor Yellow
