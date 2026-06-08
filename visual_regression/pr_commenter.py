"""
Generates a markdown report from the visual regression test results
to be posted as a comment on Pull Requests.
"""
from __future__ import annotations
import json
from pathlib import Path
from .config import WorkspacePaths

def main() -> None:
    paths = WorkspacePaths(Path(__file__).parent.parent.resolve())
    runs_dir = paths.runs_dir
    
    if not runs_dir.exists():
        print("Runs directory not found.")
        return
        
    results = []
    # Search for all result.json files in the runs directory
    for run_dir in sorted(runs_dir.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        result_json = run_dir / "result.json"
        if result_json.exists():
            try:
                data = json.loads(result_json.read_text(encoding="utf-8"))
                results.append(data)
            except Exception:
                pass
                
    if not results:
        print("No test results found.")
        return

    # Filter only runs from the latest build_id (if available)
    latest_build_id = results[0].get("build_id")
    if latest_build_id:
        results = [r for r in results if r.get("build_id") == latest_build_id]

    total = len(results)
    failures = [r for r in results if r.get("status") == "FAIL"]
    failed_count = len(failures)
    
    markdown = []
    if failed_count > 0:
        markdown.append("### 🔴 Visual Regression Detected!")
        markdown.append(f"Out of **{total}** test variations, **{failed_count}** failed pixel mismatch threshold checks.")
        markdown.append("")
        markdown.append("| Test Case | Browser | Viewport | Mismatch | Severity | AI Label |")
        markdown.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        
        for fail in failures:
            case = fail.get("case_name", "Unknown")
            cap = fail.get("capture", {})
            browser = cap.get("browser", "chromium")
            viewport = cap.get("device") or f"{cap.get('viewport', [1440, 900])[0]}px"
            
            res = fail.get("result", {})
            mismatch = res.get("mismatch_pct", 0.0)
            threshold = fail.get("threshold_pct", 0.1)
            
            ai = fail.get("ai_assessment", {})
            ai_label = ai.get("label") or "none (benign)"
            sev = fail.get("severity", {}).get("level", "medium").upper()
            
            markdown.append(f"| `{case}` | {browser} | {viewport} | **{mismatch:.2f}%** (thr: {threshold}%) | {sev} | `{ai_label}` |")
        
        markdown.append("")
        markdown.append("💡 *Download the artifacts zip file below to view full Baseline vs Current comparisons.*")
    else:
        markdown.append("### ✅ Visual Regression Passed!")
        markdown.append(f"All **{total}** test variations matched their baseline images successfully.")

    # Write output markdown comment file
    comment_file = paths.root / "pr_comment.md"
    comment_file.write_text("\n".join(markdown), encoding="utf-8")
    print(f"Generated PR comment Markdown at: {comment_file}")

if __name__ == "__main__":
    main()
