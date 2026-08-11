$ErrorActionPreference = "Stop"
$PYTHON = ".\.venv\Scripts\python.exe"

Write-Host "=== [1/2] Step 1: Fast Stabilized ResNet50 Fine-Tuning (Method 1+3) ===" -ForegroundColor Green
& $PYTHON scripts/finetune_on_live_pairs.py `
    --manifest .visual-regression/datasets/live-training-pairs-v3/manifest.json `
    --epochs 4 `
    --learning-rate 2.5e-5 `
    --max-public-images 300 `
    --samples-per-image 6 `
    --run-pair-oversample 5 `
    --dom-dropout 0.50 `
    --image-dropout 0.10 `
    --boost-class font-change=8.0 `
    --boost-class missing-element=7.0 `
    --boost-class layout-issue=6.0 `
    --boost-class broken-image=6.0 `
    --boost-class color-regression=6.0 `
    --boost-class text-issue=4.0

Write-Host "`n=== [2/2] Step 2: Running BOTH DOM & NO-DOM Evaluations Simultaneously (Parallel) ===" -ForegroundColor Green

$jobDom = Start-Job -ScriptBlock {
    Set-Location $using:PWD
    & $using:PYTHON scripts/live_eval_multiseed.py `
        --model-path .visual-regression-train/models/visual_ai_live.pt `
        --seeds 10 `
        --trials 50 `
        --out-dir reports/live-eval-unified-dom `
        --summary reports/live-eval-summary-unified-dom.json
}

$jobNoDom = Start-Job -ScriptBlock {
    Set-Location $using:PWD
    & $using:PYTHON scripts/live_eval_multiseed.py `
        --model-path .visual-regression-train/models/visual_ai_live.pt `
        --seeds 10 `
        --trials 50 `
        --no-dom `
        --out-dir reports/live-eval-unified-nodom `
        --summary reports/live-eval-summary-unified-nodom.json
}

Write-Host "Waiting for parallel DOM & NO-DOM evaluations to complete..." -ForegroundColor Yellow
$jobDom, $jobNoDom | Wait-Job | Receive-Job

Write-Host "`n=== Unified Parallel Execution Finished! Both DOM and NO-DOM Reports Ready! ===" -ForegroundColor Cyan
