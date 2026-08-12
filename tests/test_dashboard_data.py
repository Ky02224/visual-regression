import json
from pathlib import Path

from visual_regression.config import WorkspacePaths
from visual_regression.dashboard_data import build_dashboard_snapshot


def test_build_dashboard_snapshot(tmp_path: Path):
    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    paths.ensure()

    baseline_dir = paths.baselines_dir / "home"
    baseline_dir.mkdir(parents=True)
    (baseline_dir / "baseline.webp").write_bytes(b"webp")
    (baseline_dir / "metadata.json").write_text(
        json.dumps(
            {
                "name": "home",
                "created_at": "2026-03-20T00:00:00Z",
                "updated_at": "2026-03-20T00:00:00Z",
                "capture": {"url": "http://example.test", "browser": "chromium", "device": "iPhone 13", "locale": "en-US"},
                "history": [{"actor": "Alice", "timestamp": "2026-03-20T00:00:00Z"}],
            }
        ),
        encoding="utf-8",
    )
    (baseline_dir / "versions").mkdir(parents=True)
    (baseline_dir / "versions" / "manifest.json").write_text(
        json.dumps([{"version": "20260320-000000", "archived_at": "2026-03-20T00:00:00Z"}]),
        encoding="utf-8",
    )

    run_dir = paths.runs_dir / "20260320-000000_home"
    run_dir.mkdir(parents=True)
    (run_dir / "result.json").write_text(
        json.dumps(
            {
                "case_name": "home",
                "baseline_name": "home",
                "suite_name": "suite.demo.yaml",
                "status": "FAIL",
                "capture": {"url": "http://example.test", "browser": "chromium", "locale": "en-US"},
                "result": {"mismatch_pct": 1.2, "regions": [{"x": 1, "y": 2, "width": 3, "height": 4, "area": 12, "mean_delta": 10.0}]},
                "decision": {"status": "pending", "decider": "Sandra"},
                "ai_assessment": {"label": "meaningful-change", "score": 0.77},
                "ai_explanation": "CTA is missing.",
                "severity": {"label": "high", "score": 85},
                "artifacts": {"report": "report.html"},
            }
        ),
        encoding="utf-8",
    )

    (paths.models_dir / "visual_ai.json").write_text(
        json.dumps({"accuracy": 0.9, "samples": 20}),
        encoding="utf-8",
    )
    (paths.reports_dir / "suite-summary-20260320-000000.json").write_text(
        json.dumps({"passed": 3, "failed": 1, "errors": 0, "executed": 4}),
        encoding="utf-8",
    )

    snapshot = build_dashboard_snapshot(tmp_path, paths)
    assert snapshot["metrics"]["baseline_count"] == 1
    assert snapshot["metrics"]["run_count"] == 1
    assert snapshot["metrics"]["pending_decisions"] == 1
    assert snapshot["metrics"]["browser_coverage"] == 1
    assert snapshot["metrics"]["device_coverage"] == 2
    assert snapshot["metrics"]["locale_coverage"] == 1
    assert snapshot["runs"][0]["ai_label"] is None
    assert snapshot["runs"][0]["review_status"] == "unreviewed"
    assert snapshot["runs"][0]["baseline_image_href"].endswith("/baseline/home/baseline.webp")
    assert snapshot["runs"][0]["severity"]["label"] == "high"
    assert snapshot["runs"][0]["decision_status"] == "pending"
    assert snapshot["baselines"][0]["version_count"] == 1
    assert snapshot["baselines"][0]["device"] == "iPhone 13"
    assert snapshot["recent_summaries"][0]["executed"] == 4


def _run_with_deleted_baseline(paths: WorkspacePaths, run_id: str, *, write_baseline_png: bool):
    """A completed run whose baseline record no longer exists.

    Deleting or renaming a baseline is ordinary housekeeping, and the runs it
    was compared against stay on disk afterwards.
    """
    run_dir = paths.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if write_baseline_png:
        (run_dir / "baseline.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (run_dir / "result.json").write_text(
        json.dumps({
            "baseline_name": "a baseline that has since been deleted",
            "status": "FAIL",
            "result": {"mismatch_pct": 10.22, "regions": []},
            "capture": {"url": "http://example.test"},
        }),
        encoding="utf-8",
    )
    return run_dir


def test_a_run_shows_its_own_baseline_after_the_baseline_is_deleted(tmp_path: Path):
    """The detail view used to read the href off the baseline record alone.

    With the record gone it produced None, and the page rendered "Screenshot
    unavailable" over a readable baseline.png sitting in the run directory —
    the very image the run's mismatch percentage was computed against.
    """
    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    paths.ensure()
    run_id = "20260729-024143-204562_sidecar_chromium_desktop_default"
    _run_with_deleted_baseline(paths, run_id, write_baseline_png=True)

    snapshot = build_dashboard_snapshot(tmp_path, paths)
    run = next(r for r in snapshot["runs"] if r["id"] == run_id)

    assert run["baseline_image_href"] == f"/artifacts/{run_id}/baseline.png"


def test_no_href_is_offered_when_the_run_kept_no_baseline_copy(tmp_path: Path):
    """Runs written before per-run baseline copies have nothing to serve.

    Returning the path anyway would turn "no image" into a broken one, which
    is the worse of the two.
    """
    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    paths.ensure()
    run_id = "20260101-000000-000000_ancient_chromium_desktop_default"
    _run_with_deleted_baseline(paths, run_id, write_baseline_png=False)

    snapshot = build_dashboard_snapshot(tmp_path, paths)
    run = next(r for r in snapshot["runs"] if r["id"] == run_id)

    assert run["baseline_image_href"] is None
