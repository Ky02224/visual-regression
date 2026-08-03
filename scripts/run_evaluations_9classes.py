import sys
import json
from pathlib import Path

# Add visual_regression paths
sys.path.append(str(Path(__file__).resolve().parent.parent))

from visual_regression.config import WorkspacePaths, CaptureConfig
from visual_regression.baseline_manager import BaselineManager
from visual_regression.cli import _run_compare, resolve_ai_model_path

def main():
    root_path = Path(__file__).resolve().parent.parent
    workspace_paths = WorkspacePaths(root=root_path / ".visual-regression")
    workspace_paths.ensure()
    manager = BaselineManager(workspace_paths)
    
    ai_model_path = resolve_ai_model_path(workspace_paths, None, False)
    print(f"AI Model path being used: {ai_model_path}")
    
    # 9 Classifications (8 defects + benign)
    # Mapping of expected label to (baseline_name, url, defect_param)
    cases = {
        "benign": [
            ("demo-home-en", "http://127.0.0.1:8130/demo/index.html?lang=en-US", ""),
            ("demo-login-en", "http://127.0.0.1:8130/demo/login.html?lang=en-US", ""),
            ("demo-dashboard-en", "http://127.0.0.1:8130/demo/dashboard.html?lang=en-US", ""),
        ],
        "missing-element": [
            ("demo-home-en", "http://127.0.0.1:8130/demo/index.html?lang=en-US&defect=missing-cta", "missing-cta"),
            ("demo-login-en", "http://127.0.0.1:8130/demo/login.html?lang=en-US&defect=missing-cta", "missing-cta"),
            ("demo-dashboard-en", "http://127.0.0.1:8130/demo/dashboard.html?lang=en-US&defect=missing-cta", "missing-cta"),
        ],
        "layout-shift": [
            ("demo-home-en", "http://127.0.0.1:8130/demo/index.html?lang=en-US&defect=shift-card", "shift-card"),
            ("demo-login-en", "http://127.0.0.1:8130/demo/login.html?lang=en-US&defect=shift-card", "shift-card"),
            ("demo-dashboard-en", "http://127.0.0.1:8130/demo/dashboard.html?lang=en-US&defect=shift-card", "shift-card"),
        ],
        "color-regression": [
            ("demo-home-en", "http://127.0.0.1:8130/demo/index.html?lang=en-US&defect=theme-shift", "theme-shift"),
            ("demo-login-en", "http://127.0.0.1:8130/demo/login.html?lang=en-US&defect=theme-shift", "theme-shift"),
            ("demo-dashboard-en", "http://127.0.0.1:8130/demo/dashboard.html?lang=en-US&defect=theme-shift", "theme-shift"),
        ],
        "text-truncation": [
            ("demo-home-en", "http://127.0.0.1:8130/demo/index.html?lang=en-US&defect=text-truncation", "text-truncation"),
            ("demo-login-en", "http://127.0.0.1:8130/demo/login.html?lang=en-US&defect=text-truncation", "text-truncation"),
            ("demo-dashboard-en", "http://127.0.0.1:8130/demo/dashboard.html?lang=en-US&defect=text-truncation", "text-truncation"),
        ],
        "overlay-obstruction": [
            ("demo-home-en", "http://127.0.0.1:8130/demo/index.html?lang=en-US&defect=overlay-obstruction", "overlay-obstruction"),
            ("demo-login-en", "http://127.0.0.1:8130/demo/login.html?lang=en-US&defect=overlay-obstruction", "overlay-obstruction"),
            ("demo-dashboard-en", "http://127.0.0.1:8130/demo/dashboard.html?lang=en-US&defect=overlay-obstruction", "overlay-obstruction"),
        ],
        "broken-image": [
            ("demo-home-en", "http://127.0.0.1:8130/demo/index.html?lang=en-US&defect=broken-image", "broken-image"),
            ("demo-login-en", "http://127.0.0.1:8130/demo/login.html?lang=en-US&defect=broken-image", "broken-image"),
            ("demo-dashboard-en", "http://127.0.0.1:8130/demo/dashboard.html?lang=en-US&defect=broken-image", "broken-image"),
        ],
        "misaligned-fields": [
            ("demo-home-en", "http://127.0.0.1:8130/demo/index.html?lang=en-US&defect=misaligned-fields", "misaligned-fields"),
            ("demo-login-en", "http://127.0.0.1:8130/demo/login.html?lang=en-US&defect=misaligned-fields", "misaligned-fields"),
            ("demo-dashboard-en", "http://127.0.0.1:8130/demo/dashboard.html?lang=en-US&defect=misaligned-fields", "misaligned-fields"),
        ],
        "unreadable-text": [
            ("demo-home-en", "http://127.0.0.1:8130/demo/index.html?lang=en-US&defect=unreadable-text", "unreadable-text"),
            ("demo-login-en", "http://127.0.0.1:8130/demo/login.html?lang=en-US&defect=unreadable-text", "unreadable-text"),
            ("demo-dashboard-en", "http://127.0.0.1:8130/demo/dashboard.html?lang=en-US&defect=unreadable-text", "unreadable-text"),
        ],
    }
    
    results = []
    
    for expected_label, test_cases in cases.items():
        print(f"\n========================================\nRunning cases for classification: {expected_label}\n========================================")
        for baseline_name, url, defect in test_cases:
            print(f"Running: baseline={baseline_name}, url={url}")
            cfg = CaptureConfig(
                name=baseline_name,
                url=url,
                browser="chromium",
                viewport=(1440, 900),
                hide_selectors=[".defect-banner"],
            )
            try:
                passed, run_path, extra = _run_compare(
                    manager=manager,
                    paths=workspace_paths,
                    case_name=baseline_name,
                    capture_cfg=cfg,
                    threshold_pct=0.25,
                    pixel_threshold=20,
                    min_region_area=120,
                    ignore_regions=[],
                    ai_model_path=ai_model_path,
                )
                
                ai_label = extra.get("ai_label") or "benign"
                ai_score = extra.get("ai_score") or 1.0
                mismatch_pct = extra.get("mismatch_pct", 0.0)
                diff_regions = extra.get("diff_regions", 0)

                # The model emits a mix of consolidated ("text-issue") and raw
                # ("layout-shift") labels depending on the veto path, so score
                # both sides in the consolidated class space.
                from visual_regression.ai_training import _consolidate_label

                def _to_consolidated(name: str) -> str:
                    if name in {"benign", "no-change"}:
                        name = "insignificant-change"
                    return _consolidate_label(name)

                simplified_expected = _to_consolidated(expected_label)
                simplified_predicted = _to_consolidated(ai_label)

                is_correct = (simplified_predicted == simplified_expected)
                results.append({
                    "expected": expected_label,
                    "baseline": baseline_name,
                    "defect": defect,
                    "ai_label": ai_label,
                    "ai_score": ai_score,
                    "mismatch_pct": mismatch_pct,
                    "diff_regions": diff_regions,
                    "passed": passed,
                    "status": "CORRECT" if is_correct else "MISCLASSIFIED"
                })
                print(f"-> Expected: {expected_label} (simplified: {simplified_expected}) | AI Predicted: {ai_label} (score={ai_score:.4f}) | Result: {'CORRECT' if is_correct else 'MISCLASSIFIED'}")
            except Exception as e:
                print(f"-> Error running comparison: {e}")
                results.append({
                    "expected": expected_label,
                    "baseline": baseline_name,
                    "defect": defect,
                    "ai_label": "error",
                    "ai_score": 0.0,
                    "mismatch_pct": 0.0,
                    "diff_regions": 0,
                    "passed": False,
                    "status": f"ERROR: {str(e)}"
                })

    # Save results to a JSON file
    out_file = root_path / "scratch" / "eval_9classes_results.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nAll evaluations finished! Results saved to {out_file}")

if __name__ == "__main__":
    main()
