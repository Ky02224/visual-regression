"""cmd_check_ci ("The Lens" CI/CD gatekeeper) used to always pass:

it read `data.get("assessments", [])`, but result.json never has an
"assessments" key — severity is stored as a single `{"label": ..., "score":
...}` dict under "severity" (see summarize_severity). So `assessments` was
always `[]`, and check-ci printed "BUILD PASSED" and returned 0 no matter how
severe the real regression was.

It also only inspected the single most-recently-modified run directory
rather than every run belonging to the just-completed build, so even a
fixed severity-reading path would miss a severe regression in any case
other than whichever one a parallel capture worker happened to finish last.
"""
import argparse
import json
import time
from pathlib import Path

import pytest

from visual_regression.cli import cmd_check_ci
from visual_regression.config import WorkspacePaths


@pytest.fixture
def paths(tmp_path):
    p = WorkspacePaths(root=tmp_path / ".visual-regression")
    p.ensure()
    return p


def _write_run(paths: WorkspacePaths, name: str, *, build_id: str, severity_label: str, case_name: str = "demo", status: str | None = None) -> None:
    run_dir = paths.runs_dir / name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "result.json").write_text(json.dumps({
        "case_name": case_name,
        "build_id": build_id,
        "status": status if status is not None else ("FAIL" if severity_label != "low" else "PASS"),
        "severity": {"label": severity_label, "score": {"low": 0, "medium": 3, "high": 5}[severity_label]},
    }), encoding="utf-8")
    # Ensure distinct, increasing mtimes so run ordering is deterministic.
    time.sleep(0.01)


def _args(max_severity: str = "high") -> argparse.Namespace:
    return argparse.Namespace(max_severity=max_severity, viewports="desktop")


def test_high_severity_run_fails_the_build(paths):
    _write_run(paths, "run-1", build_id="build-A", severity_label="low")
    _write_run(paths, "run-2", build_id="build-A", severity_label="high")

    assert cmd_check_ci(_args(), paths) == 1


def test_all_low_severity_passes(paths):
    _write_run(paths, "run-1", build_id="build-A", severity_label="low")
    _write_run(paths, "run-2", build_id="build-A", severity_label="low")

    assert cmd_check_ci(_args(), paths) == 0


def test_severity_in_non_latest_run_of_the_build_still_fails(paths):
    """The regression is in the *first*-written (not most-recently-modified)
    run of the build — this is exactly the scenario a single-run check
    would miss under parallel capture workers finishing in a different
    order than case index."""
    _write_run(paths, "run-1", build_id="build-A", severity_label="high")
    _write_run(paths, "run-2", build_id="build-A", severity_label="low")

    assert cmd_check_ci(_args(), paths) == 1


def test_failed_status_blocks_even_with_medium_severity(paths):
    # A DOM-diff-confirmed defect with a small pixel footprint can
    # legitimately score as "medium" under summarize_severity's heuristic
    # (below the default "high" --max-severity threshold) while still being
    # a real, confirmed regression per decide_pass_fail's status field.
    # Regression test for a real bug found via manual verification: this
    # gate used to look at severity alone and ignore status entirely, so a
    # run the platform itself already confirmed as FAIL could still pass
    # the actual mechanism real CI pipelines call to block a deploy.
    _write_run(paths, "run-1", build_id="build-A", severity_label="medium", status="FAIL")

    assert cmd_check_ci(_args(max_severity="high"), paths) == 1


def test_severity_from_a_different_build_is_ignored(paths):
    _write_run(paths, "old-run", build_id="build-OLD", severity_label="high")
    _write_run(paths, "new-run", build_id="build-NEW", severity_label="low")

    assert cmd_check_ci(_args(), paths) == 0
