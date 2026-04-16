from pathlib import Path
import json

from visual_regression.config import WorkspacePaths
from visual_regression.review_manager import ReviewManager


def test_delete_run_removes_run_directory(tmp_path: Path):
    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    manager = ReviewManager(paths)
    run_dir = paths.runs_dir / "demo-run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "result.json").write_text("{}", encoding="utf-8")

    result = manager.delete_run("demo-run")

    assert result["deleted"] is True
    assert not run_dir.exists()


def test_save_decision_appends_decision_history(tmp_path: Path):
    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    manager = ReviewManager(paths)
    run_dir = paths.runs_dir / "demo-run"
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "case_name": "demo",
        "status": "FAIL",
        "result": {
            "baseline_size": [100, 100],
            "current_size": [100, 100],
            "diff_pixels": 10,
            "total_pixels": 10000,
            "mismatch_pct": 0.1,
            "ssim_score": 0.99,
            "regions": [],
        },
        "artifacts": {
            "baseline": "baseline.png",
            "current": "current.png",
            "diff_overlay": "diff_overlay.png",
            "binary_diff": "binary_diff.png",
            "report": str(run_dir / "report.html"),
        },
        "capture": {"url": "https://example.com", "browser": "chromium"},
        "decision": {"status": "pending"},
    }
    (run_dir / "result.json").write_text(json.dumps(payload), encoding="utf-8")

    manager.save_decision(run_dir, "approved", "lead", "looks good")
    updated = manager.load_run_payload(run_dir)

    assert updated["decision"]["status"] == "approved"
    assert len(updated["decision_history"]) == 2
    assert updated["decision_history"][0]["status"] == "pending"
    assert updated["decision_history"][1]["status"] == "approved"
