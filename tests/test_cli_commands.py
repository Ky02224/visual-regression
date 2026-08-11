"""Tests for the CLI command bodies.

cli.py was 14% covered — 1036 of its 1200 statements never executed by a test.
The capture commands drive a real browser, so those are covered here with the
capture step patched out; what is under test is the argument handling, metadata
recording and error paths around it, which is where the bugs that reach users
actually live.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from visual_regression.baseline_manager import BaselineManager
from visual_regression.cli import (
    cmd_check_ci,
    cmd_create_baseline,
    cmd_list_baselines,
    cmd_list_runs,
    cmd_review_run,
    cmd_update_baseline,
)
from visual_regression.config import WorkspacePaths


@pytest.fixture
def paths(tmp_path):
    paths = WorkspacePaths(tmp_path / ".visual-regression")
    paths.ensure()
    return paths


@pytest.fixture
def manager(paths):
    return BaselineManager(paths)


@pytest.fixture
def png(tmp_path):
    path = tmp_path / "shot.png"
    ok, buf = cv2.imencode(".png", np.full((60, 80, 3), 180, dtype=np.uint8))
    assert ok
    path.write_bytes(buf.tobytes())
    return path


def _args(**overrides):
    base = dict(
        name="home", url=None, image=None, updated_by="tester",
        browser="chromium", device=None, viewport="1440x900", wait_ms=0,
        wait_until="load", timeout_ms=15000, no_full_page=False,
        allow_animations=False, locale=None, timezone_id=None,
        color_scheme="light", header=[], hide_selector=[], wait_for_selector=None,
        mock_route=[], login_url=None, login_username=None, login_password=None,
        username_selector=None, password_selector=None, submit_selector=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


_RESULT_BLOCK = {
    "baseline_size": [800, 600], "current_size": [800, 600],
    "diff_pixels": 100, "total_pixels": 480_000, "mismatch_pct": 0.02,
    "ssim_score": 0.99, "regions": [],
}


def _write_run(paths, name, payload, *, with_result=True):
    """Write a run's result.json.

    `result` is included by default because every real run has it — reviewing a
    run regenerates its HTML report from this payload.
    """
    run_dir = paths.runs_dir / name
    run_dir.mkdir(parents=True, exist_ok=True)
    full = {"result": dict(_RESULT_BLOCK), **payload} if with_result else dict(payload)
    (run_dir / "result.json").write_text(json.dumps(full), encoding="utf-8")
    return run_dir


# ---------------------------------------------------------------------------
# create-baseline / update-baseline
# ---------------------------------------------------------------------------

class TestCreateBaseline:
    def test_creates_from_a_local_image(self, manager, paths, png, capsys):
        assert cmd_create_baseline(_args(image=str(png)), manager, paths) == 0
        assert manager.exists("home")
        assert "created from local image" in capsys.readouterr().out

    def test_records_the_source_in_metadata(self, manager, paths, png):
        """Provenance matters: a baseline captured from a file and one captured
        from a URL are not interchangeable when someone later re-captures."""
        cmd_create_baseline(_args(image=str(png)), manager, paths)
        assert manager.load_metadata("home")["capture"]["source"] == "local-image"

    def test_records_who_updated_it(self, manager, paths, png):
        cmd_create_baseline(_args(image=str(png), updated_by="alice"), manager, paths)
        assert manager.load_metadata("home")["capture"]["updated_by"] == "alice"

    def test_a_missing_image_is_rejected(self, manager, paths, tmp_path):
        with pytest.raises(FileNotFoundError, match="Image not found"):
            cmd_create_baseline(_args(image=str(tmp_path / "absent.png")), manager, paths)

    def test_neither_url_nor_image_is_rejected(self, manager, paths):
        with pytest.raises(ValueError, match="requires --url"):
            cmd_create_baseline(_args(), manager, paths)

    def test_a_url_goes_through_the_capture_path(self, manager, paths, monkeypatch, png):
        captured = {}

        def fake_capture(manager, paths, name, capture_cfg, capture_meta):
            captured["url"] = capture_cfg.url
            captured["source"] = capture_meta["source"]
            manager.save_from_image(name, png, capture_meta)

        monkeypatch.setattr("visual_regression.cli._capture_and_save_baseline", fake_capture)

        assert cmd_create_baseline(_args(url="https://example.com"), manager, paths) == 0
        assert captured["url"] == "https://example.com"
        assert captured["source"] == "website-capture"


class TestUpdateBaseline:
    def test_updates_from_a_local_image(self, manager, paths, png, capsys):
        cmd_create_baseline(_args(image=str(png)), manager, paths)
        assert cmd_update_baseline(_args(image=str(png)), manager, paths) == 0
        assert "updated from local image" in capsys.readouterr().out

    def test_reuses_the_url_recorded_on_the_existing_baseline(self, manager, paths, png, monkeypatch):
        """`update-baseline --name x` with no URL has to re-capture the same page,
        or it would silently baseline something else."""
        captured = {}

        def fake_capture(manager, paths, name, capture_cfg, capture_meta):
            captured["url"] = capture_cfg.url
            manager.save_from_image(name, png, capture_meta)

        monkeypatch.setattr("visual_regression.cli._capture_and_save_baseline", fake_capture)
        cmd_create_baseline(_args(url="https://example.com/page"), manager, paths)
        captured.clear()

        cmd_update_baseline(_args(url=None), manager, paths)

        assert captured["url"] == "https://example.com/page"

    def test_an_explicit_url_overrides_the_stored_one(self, manager, paths, png, monkeypatch):
        captured = {}

        def fake_capture(manager, paths, name, capture_cfg, capture_meta):
            captured["url"] = capture_cfg.url
            manager.save_from_image(name, png, capture_meta)

        monkeypatch.setattr("visual_regression.cli._capture_and_save_baseline", fake_capture)
        cmd_create_baseline(_args(url="https://old.example.com"), manager, paths)

        cmd_update_baseline(_args(url="https://new.example.com"), manager, paths)

        assert captured["url"] == "https://new.example.com"

    def test_no_url_and_no_existing_baseline_is_rejected(self, manager, paths):
        with pytest.raises(ValueError, match="requires --url"):
            cmd_update_baseline(_args(name="never-made"), manager, paths)

    def test_a_missing_image_is_rejected(self, manager, paths, tmp_path):
        with pytest.raises(FileNotFoundError):
            cmd_update_baseline(_args(image=str(tmp_path / "absent.png")), manager, paths)


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------

class TestListing:
    def test_list_baselines_reports_an_empty_workspace(self, manager, capsys):
        assert cmd_list_baselines(manager) == 0
        assert "No baselines found" in capsys.readouterr().out

    def test_list_baselines_prints_each_name(self, manager, paths, png, capsys):
        cmd_create_baseline(_args(name="home", image=str(png)), manager, paths)
        cmd_create_baseline(_args(name="login", image=str(png)), manager, paths)

        cmd_list_baselines(manager)

        out = capsys.readouterr().out
        assert "home" in out and "login" in out

    def test_list_runs_reports_an_empty_workspace(self, paths, capsys):
        assert cmd_list_runs(paths) == 0
        assert "No runs" in capsys.readouterr().out or "no runs" in capsys.readouterr().out.lower()


# ---------------------------------------------------------------------------
# check-ci — the gate that blocks a deploy
# ---------------------------------------------------------------------------

class TestCheckCi:
    def test_passes_when_there_are_no_runs(self, paths):
        assert cmd_check_ci(_args(max_severity="high"), paths) == 0

    def test_passes_a_clean_build(self, paths):
        _write_run(paths, "20260101-000001_a", {
            "build_id": "b1", "status": "PASS", "case_name": "home",
            "severity": {"label": "low"},
        })
        assert cmd_check_ci(_args(max_severity="high"), paths) == 0

    def test_blocks_on_a_failed_comparison_regardless_of_severity(self, paths, capsys):
        """A DOM-confirmed defect with a small pixel footprint scores as medium
        severity, which sits below the default threshold — but the platform
        already called it a regression, so it must still block."""
        _write_run(paths, "20260101-000001_a", {
            "build_id": "b1", "status": "FAIL", "case_name": "checkout",
            "severity": {"label": "medium"},
            "ai_assessment": {"label": "text-issue"},
        })

        assert cmd_check_ci(_args(max_severity="high"), paths) == 1
        assert "CI BLOCKER" in capsys.readouterr().out

    def test_blocks_on_a_high_severity_run_that_passed_its_own_comparison(self, paths):
        _write_run(paths, "20260101-000001_a", {
            "build_id": "b1", "status": "PASS", "case_name": "home",
            "severity": {"label": "high"},
        })
        assert cmd_check_ci(_args(max_severity="high"), paths) == 1

    def test_the_threshold_is_configurable(self, paths):
        _write_run(paths, "20260101-000001_a", {
            "build_id": "b1", "status": "PASS", "case_name": "home",
            "severity": {"label": "medium"},
        })
        assert cmd_check_ci(_args(max_severity="high"), paths) == 0
        assert cmd_check_ci(_args(max_severity="medium"), paths) == 1

    def test_gates_on_every_run_in_the_build_not_just_the_newest(self, paths):
        """A suite writes one directory per case, all sharing a build_id, and
        parallel workers mean any case can finish last. Gating on the
        most-recently-modified directory alone would miss the failure."""
        _write_run(paths, "20260101-000001_bad", {
            "build_id": "b1", "status": "FAIL", "case_name": "checkout",
            "severity": {"label": "high"},
        })
        _write_run(paths, "20260101-000002_good", {
            "build_id": "b1", "status": "PASS", "case_name": "home",
            "severity": {"label": "low"},
        })

        assert cmd_check_ci(_args(max_severity="high"), paths) == 1

    def test_picks_the_newest_build_when_mtimes_tie(self, paths):
        """Two runs sharing an mtime must still order by name.

        The gate used to sort on st_mtime. A suite writes its run directories
        milliseconds apart, and on a filesystem that stores whole seconds --
        ext4 on the CI runner -- those become equal keys, so which build looked
        newest depended on directory order. It failed intermittently there and
        never on Windows, whose 100ns timestamps never tie. Setting both mtimes
        to the same value reproduces the CI condition on any platform.

        Getting this wrong blocks a green build on a previous build's failure,
        which is the expensive direction to be wrong in.
        """
        old = _write_run(paths, "20260101-000001_old", {
            "build_id": "b0", "status": "FAIL", "case_name": "stale",
            "severity": {"label": "high"},
        })
        new = _write_run(paths, "20260101-000002_new", {
            "build_id": "b1", "status": "PASS", "case_name": "home",
            "severity": {"label": "low"},
        })
        shared = 1_700_000_000
        for d in (old, new):
            os.utime(d, (shared, shared))

        assert cmd_check_ci(_args(max_severity="high"), paths) == 0

    def test_ignores_runs_from_a_different_build(self, paths):
        _write_run(paths, "20260101-000001_old", {
            "build_id": "b0", "status": "FAIL", "case_name": "stale",
            "severity": {"label": "high"},
        })
        _write_run(paths, "20260101-000002_new", {
            "build_id": "b1", "status": "PASS", "case_name": "home",
            "severity": {"label": "low"},
        })

        assert cmd_check_ci(_args(max_severity="high"), paths) == 0

    def test_an_unreadable_result_does_not_crash_the_gate(self, paths):
        run_dir = paths.runs_dir / "20260101-000001_bad"
        run_dir.mkdir(parents=True)
        (run_dir / "result.json").write_text("{not json", encoding="utf-8")
        assert cmd_check_ci(_args(max_severity="high"), paths) == 0

    def test_a_missing_severity_defaults_to_low_rather_than_blocking(self, paths):
        _write_run(paths, "20260101-000001_a", {"build_id": "b1", "status": "PASS", "case_name": "home"})
        assert cmd_check_ci(_args(max_severity="high"), paths) == 0


# ---------------------------------------------------------------------------
# review-run
# ---------------------------------------------------------------------------

class TestReviewRun:
    def test_records_an_approval(self, paths):
        _write_run(paths, "run-1", {"status": "FAIL", "case_name": "home"})
        rc = cmd_review_run(
            _args(run="run-1", decision="approved", reviewer="alice", comment="intended"), paths
        )
        assert rc == 0
        payload = json.loads((paths.runs_dir / "run-1" / "result.json").read_text(encoding="utf-8"))
        assert payload["decision"]["status"] == "approved"

    def test_records_a_rejection(self, paths):
        _write_run(paths, "run-1", {"status": "FAIL", "case_name": "home"})
        cmd_review_run(_args(run="run-1", decision="rejected", reviewer="bob", comment=""), paths)
        payload = json.loads((paths.runs_dir / "run-1" / "result.json").read_text(encoding="utf-8"))
        assert payload["decision"]["status"] == "rejected"
