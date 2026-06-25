"""
Generates a markdown report from the visual regression test results
to be posted as a comment on Pull Requests and sets GitHub Commit Status.
"""
from __future__ import annotations
import json
from pathlib import Path
from .config import WorkspacePaths

def post_to_github(markdown_body: str, is_fail: bool, failed_count: int, total_count: int) -> None:
    import os
    import urllib.request
    import json as _json

    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    sha = os.environ.get("GITHUB_SHA")
    dashboard_url = os.environ.get("VISUAL_DASHBOARD_URL")

    if not token or not repo:
        print("GitHub integration skipped: GITHUB_TOKEN or GITHUB_REPOSITORY not set in environment.")
        return

    # 1. Update Commit Status
    if sha:
        status_url = f"https://api.github.com/repos/{repo}/statuses/{sha}"
        status_data = {
            "state": "failure" if is_fail else "success",
            "context": "visual-regression/mismatch-check",
            "description": f"{failed_count} failures detected" if is_fail else "All snapshots matched successfully",
        }
        if dashboard_url:
            status_data["target_url"] = dashboard_url

        try:
            req = urllib.request.Request(
                status_url,
                data=_json.dumps(status_data).encode("utf-8"),
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "Python-VisualRegression-Workbench",
                    "Content-Type": "application/json",
                },
                method="POST"
            )
            with urllib.request.urlopen(req) as resp:
                print(f"GitHub Commit Status updated successfully (HTTP {resp.status})")
        except Exception as e:
            print(f"Error updating GitHub Commit Status: {e}")

    # 2. Post PR Comment (if PR number is available)
    pr_number = None
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path and os.path.exists(event_path):
        try:
            with open(event_path, "r", encoding="utf-8") as f:
                event_data = _json.load(f)
            pr_number = event_data.get("pull_request", {}).get("number")
        except Exception:
            pass

    if not pr_number:
        # Fallback to parse from GITHUB_REF
        ref = os.environ.get("GITHUB_REF", "")
        if ref.startswith("refs/pull/"):
            parts = ref.split("/")
            if len(parts) > 2:
                try:
                    pr_number = int(parts[2])
                except ValueError:
                    pass

    if pr_number:
        comment_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
        comment_data = {
            "body": markdown_body
        }
        try:
            req = urllib.request.Request(
                comment_url,
                data=_json.dumps(comment_data).encode("utf-8"),
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "Python-VisualRegression-Workbench",
                    "Content-Type": "application/json",
                },
                method="POST"
            )
            with urllib.request.urlopen(req) as resp:
                print(f"GitHub PR comment posted successfully (HTTP {resp.status})")
        except Exception as e:
            print(f"Error posting GitHub PR comment: {e}")

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

    markdown_content = "\n".join(markdown)

    # Write output markdown comment file
    comment_file = paths.root / "pr_comment.md"
    comment_file.write_text(markdown_content, encoding="utf-8")
    print(f"Generated PR comment Markdown at: {comment_file}")

    # Post/publish to GitHub CI environment if config is present
    post_to_github(markdown_content, failed_count > 0, failed_count, total)

if __name__ == "__main__":
    main()
