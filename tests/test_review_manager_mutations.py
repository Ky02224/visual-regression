from pathlib import Path
import json

import pytest

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
            "baseline": "baseline.webp",
            "current": "current.webp",
            "diff_overlay": "diff_overlay.webp",
            "binary_diff": "binary_diff.webp",
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


def test_resolve_run_dir_rejects_paths_outside_runs_dir(tmp_path: Path):
    """resolve_run_dir used to accept run_ref as a raw filesystem path — if
    Path(run_ref) happened to exist and be a directory, it was returned as-is
    with no confinement check at all. Since run_ref comes straight from
    request payloads (bulk review, single review), "../../something-real"
    could resolve outside runs_dir entirely. Only delete_run added its own
    containment check afterward; save_decision/load_run_payload did not."""
    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    manager = ReviewManager(paths)

    # A real directory that exists on disk but lives outside runs_dir.
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "result.json").write_text("{}", encoding="utf-8")

    # `assert False` here would be compiled out under `python -O`, turning both
    # of these traversal checks into silent no-ops.
    traversal_ref = str(Path("..") / "outside")
    with pytest.raises(FileNotFoundError):
        manager.resolve_run_dir(traversal_ref)

    # An absolute path to the same outside directory must also be rejected.
    with pytest.raises(FileNotFoundError):
        manager.resolve_run_dir(str(outside_dir))

    # A legitimate bare run name under runs_dir still resolves normally.
    run_dir = paths.runs_dir / "demo-run"
    run_dir.mkdir(parents=True, exist_ok=True)
    assert manager.resolve_run_dir("demo-run") == run_dir
