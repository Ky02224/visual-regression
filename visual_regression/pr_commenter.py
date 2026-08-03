"""
Generates a markdown report from the visual regression test results
to be posted as a comment on Pull Requests and sets GitHub Commit Status.
"""
from __future__ import annotations
import json
from pathlib import Path
from .config import WorkspacePaths

# HTTP status codes that indicate a request will never succeed on retry
# (bad/expired token, missing permissions, wrong repo/PR) — retrying just
# wastes time up to the full backoff budget for no benefit.
_NON_RETRIABLE_HTTP_CODES = {400, 401, 403, 404, 422}


def _is_permanent_error(exc: Exception) -> bool:
    import urllib.error
    return isinstance(exc, urllib.error.HTTPError) and exc.code in _NON_RETRIABLE_HTTP_CODES


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

    # Update Commit Status
    import time
    max_retries = 3
    retry_delay = 2.0

    if sha:
        status_url = f"https://api.github.com/repos/{repo}/statuses/{sha}"
        status_data = {
            "state": "failure" if is_fail else "success",
            "context": "visual-regression/mismatch-check",
            "description": f"{failed_count} failures detected" if is_fail else "All snapshots matched successfully",
        }
        if dashboard_url:
            status_data["target_url"] = dashboard_url

        for attempt in range(1, max_retries + 1):
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
                with urllib.request.urlopen(req, timeout=10) as resp:
                    print(f"GitHub Commit Status updated successfully (HTTP {resp.status})")
                    break
            except Exception as e:
                if attempt == max_retries or _is_permanent_error(e):
                    print(f"Error updating GitHub Commit Status (not retrying): {e}")
                    break
                else:
                    delay = retry_delay * (2 ** (attempt - 1))
                    print(f"Error updating GitHub Commit Status: {e}. Retrying in {delay}s (Attempt {attempt}/{max_retries})...")
                    time.sleep(delay)

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
        for attempt in range(1, max_retries + 1):
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
                with urllib.request.urlopen(req, timeout=10) as resp:
                    print(f"GitHub PR comment posted successfully (HTTP {resp.status})")
                    break
            except Exception as e:
                if attempt == max_retries or _is_permanent_error(e):
                    print(f"Error posting GitHub PR comment (not retrying): {e}")
                    break
                else:
                    delay = retry_delay * (2 ** (attempt - 1))
                    print(f"Error posting GitHub PR comment: {e}. Retrying in {delay}s (Attempt {attempt}/{max_retries})...")
                    time.sleep(delay)

def main(paths: WorkspacePaths | None = None) -> None:
    # `paths` is injectable so this can be exercised against a temp workspace.
    # Resolving it from __file__ unconditionally made the whole function
    # untestable: it always pointed at the developer's real .visual-regression.
    if paths is None:
        paths = WorkspacePaths(root=Path(__file__).parent.parent.resolve() / ".visual-regression")
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
            except Exception as e:
                print(f"[WARN] Skipping unreadable run result {result_json}: {e}")
                
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
