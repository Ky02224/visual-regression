# pack_for_colab.ps1
# 只打包训练所需的文件，排除 scratch/、.venv/、node_modules/ 等大型目录
# 运行方法：右键 → 用 PowerShell 运行，或在终端执行 .\pack_for_colab.ps1

$root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$output  = Join-Path ([Environment]::GetFolderPath("Desktop")) "FYP_VISUAL_colab.zip"

$exclude = @(
    "$root\scratch",
    "$root\.venv",
    "$root\.tmp_figma_review",
    "$root\.tmp_ai_studio_review",
    "$root\dashboard_frontend\node_modules",
    "$root\.visual-regression\models",
    "$root\__pycache__",
    "$root\.pytest_cache"
)

Write-Host "📦 打包中（排除大型目录）..." -ForegroundColor Cyan

if (Test-Path $output) { Remove-Item $output -Force }

Add-Type -AssemblyName System.IO.Compression.FileSystem

$zip = [System.IO.Compression.ZipFile]::Open($output, 'Create')

$items = Get-ChildItem -Path $root -Recurse -File | Where-Object {
    $path = $_.FullName
    $skip = $false
    foreach ($ex in $exclude) {
        if ($path.StartsWith($ex)) { $skip = $true; break }
    }
    # 跳过 Python 缓存文件
    if ($_.Name -match '__pycache__|\.pyc$|\.pyo$') { $skip = $true }
    -not $skip
}

$count = 0
foreach ($file in $items) {
    $relative = $file.FullName.Substring($root.Length + 1)
    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
        $zip, $file.FullName, $relative,
        [System.IO.Compression.CompressionLevel]::Optimal
    ) | Out-Null
    $count++
    if ($count % 50 -eq 0) { Write-Host "  已处理 $count 个文件..." }
}

$zip.Dispose()

$sizeMB = [math]::Round((Get-Item $output).Length / 1MB, 1)
Write-Host ""
Write-Host "✅ 打包完成！" -ForegroundColor Green
Write-Host "   文件: $output"
Write-Host "   大小: $sizeMB MB（共 $count 个文件）"
Write-Host ""
Write-Host "📤 下一步：把 FYP_VISUAL_colab.zip 上传到 Google Drive 根目录" -ForegroundColor Yellow
