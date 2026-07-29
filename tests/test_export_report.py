"""generate_standalone_report used to crash on SKIP/ERROR run rows.

cli.py's run-suite persists mismatch_pct/diff_pixels as an explicit JSON
`null` (not an absent key) for SKIP (fail-fast) and ERROR (capture failed)
rows. `result.get("mismatch_pct", 0)` only applies its default when the key
is *missing*, not when it's present with value None, so `float(None)` and
`f"{None:,}"` raised TypeError — crashing the export for exactly the runs
where a human most needs to see what happened.
"""
import json
from pathlib import Path

from visual_regression.export_report import generate_standalone_report


def _write_run(run_dir: Path, payload: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "result.json").write_text(json.dumps(payload), encoding="utf-8")


def test_export_skip_row_with_null_mismatch(tmp_path: Path):
    run_dir = tmp_path / "run-skip"
    _write_run(run_dir, {
        "case_name": "demo",
        "status": "SKIP",
        "message": "Skipped due to fail-fast",
        "result": {"mismatch_pct": None, "diff_pixels": None},
    })

    html = generate_standalone_report(run_dir)

    assert "demo" in html
    assert "0.00%" in html


def test_export_error_row_with_missing_result(tmp_path: Path):
    run_dir = tmp_path / "run-error"
    _write_run(run_dir, {
        "case_name": "demo",
        "status": "ERROR",
        "message": "Capture failed",
    })

    html = generate_standalone_report(run_dir)

    assert "demo" in html


def test_export_normal_passing_run(tmp_path: Path):
    run_dir = tmp_path / "run-pass"
    _write_run(run_dir, {
        "case_name": "demo",
        "status": "PASS",
        "result": {"mismatch_pct": 0.05, "diff_pixels": 12, "regions": []},
    })

    html = generate_standalone_report(run_dir)

    assert "0.05%" in html
