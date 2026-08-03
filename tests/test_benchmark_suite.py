"""Regression tests for the pieces that make an injected-defect benchmark honest.

Each of these guards a specific way the benchmark silently stopped proving
anything:

* `baseline_url` — without it a defect case captures its baseline from the very
  URL it then compares against, so the images are identical and the case passes
  no matter how broken the page is. That is how all 108 cases in the previous
  benchmark passed.
* the run-pair train/eval split — one loader fed both training and evaluation,
  so the reported "real run" accuracy was a training-set score.
* `_is_known_defect_label` — the old membership test dropped every
  consolidated-only label, i.e. exactly the layout-issue and text-issue runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from visual_regression.ai_training import (
    RUN_PAIR_EVAL_FRACTION,
    _is_known_defect_label,
    _run_pair_split,
)
from visual_regression.suite_runner import load_suite


def _write_suite(tmp_path: Path, tests: list[dict], defaults: dict | None = None) -> Path:
    payload: dict = {"tests": tests}
    if defaults:
        payload["defaults"] = defaults
    path = tmp_path / "suite.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


class TestBaselineUrl:
    def test_baseline_url_is_parsed_when_present(self, tmp_path):
        suite = _write_suite(tmp_path, [{
            "name": "case-defect",
            "url": "http://host/page.html?defect=missing-cta",
            "baseline_url": "http://host/page.html",
        }])
        case = load_suite(suite)[0]
        assert case.url == "http://host/page.html?defect=missing-cta"
        assert case.baseline_url == "http://host/page.html"

    def test_baseline_url_defaults_to_none(self, tmp_path):
        suite = _write_suite(tmp_path, [{"name": "case", "url": "http://host/page.html"}])
        assert load_suite(suite)[0].baseline_url is None

    def test_baseline_url_can_come_from_defaults(self, tmp_path):
        suite = _write_suite(
            tmp_path,
            [{"name": "case", "url": "http://host/page.html?defect=theme-shift"}],
            defaults={"baseline_url": "http://host/page.html"},
        )
        assert load_suite(suite)[0].baseline_url == "http://host/page.html"

    def test_capture_config_uses_baseline_url_only_for_baselines(self, tmp_path):
        """The baseline capture must hit the clean page, the run the defective one.

        Everything else about the two captures has to stay identical, or the
        diff would show viewport/locale differences rather than the defect.
        """
        from types import SimpleNamespace

        from visual_regression.cli import _capture_config_from_case

        suite = _write_suite(tmp_path, [{
            "name": "case-defect",
            "url": "http://host/page.html?defect=missing-cta",
            "baseline_url": "http://host/page.html",
            "locale": "zh-CN",
            "viewport": [1280, 720],
        }])
        case = load_suite(suite)[0]
        args = SimpleNamespace(
            timeout_ms=15000, no_full_page=False, allow_animations=False,
            login_url=None, login_username=None, login_password=None,
            username_selector=None, password_selector=None, submit_selector=None,
        )

        baseline_cfg = _capture_config_from_case(case, args, for_baseline=True)
        run_cfg = _capture_config_from_case(case, args)

        assert baseline_cfg.url == "http://host/page.html"
        assert run_cfg.url == "http://host/page.html?defect=missing-cta"
        assert baseline_cfg.locale == run_cfg.locale == "zh-CN"
        assert baseline_cfg.viewport == run_cfg.viewport == (1280, 720)

    def test_capture_config_falls_back_to_url_without_baseline_url(self, tmp_path):
        from types import SimpleNamespace

        from visual_regression.cli import _capture_config_from_case

        suite = _write_suite(tmp_path, [{"name": "case", "url": "http://host/page.html"}])
        case = load_suite(suite)[0]
        args = SimpleNamespace(
            timeout_ms=15000, no_full_page=False, allow_animations=False,
            login_url=None, login_username=None, login_password=None,
            username_selector=None, password_selector=None, submit_selector=None,
        )
        cfg = _capture_config_from_case(case, args, for_baseline=True)
        assert cfg.url == "http://host/page.html"


class TestRunPairSplit:
    def test_split_is_deterministic(self):
        assert _run_pair_split("20260730-1200-abc_case") == _run_pair_split("20260730-1200-abc_case")

    def test_split_only_returns_train_or_eval(self):
        assert {_run_pair_split(f"run-{i}") for i in range(200)} <= {"train", "eval"}

    def test_split_roughly_matches_the_target_fraction(self):
        names = [f"20260730-{i:06d}_case-{i}" for i in range(4000)]
        eval_share = sum(1 for n in names if _run_pair_split(n) == "eval") / len(names)
        assert abs(eval_share - RUN_PAIR_EVAL_FRACTION) < 0.03

    def test_train_and_eval_sets_are_disjoint(self):
        names = [f"run-{i}" for i in range(500)]
        train = {n for n in names if _run_pair_split(n) == "train"}
        held_out = {n for n in names if _run_pair_split(n) == "eval"}
        assert train & held_out == set()
        assert train | held_out == set(names)

    def test_loader_rejects_an_unknown_split(self, tmp_path):
        from visual_regression.ai_training import _load_run_pair_samples
        from visual_regression.config import WorkspacePaths

        paths = WorkspacePaths(tmp_path)
        paths.ensure()
        with pytest.raises(ValueError, match="split must be one of"):
            _load_run_pair_samples(paths, pixel_threshold=20, min_region_area=120, split="validation")


class TestKnownDefectLabel:
    @pytest.mark.parametrize("label", ["layout-issue", "text-issue", "missing-element", "font-change"])
    def test_consolidated_labels_are_accepted(self, label):
        """These are what ai_assessment.label actually holds; the old raw-taxonomy
        membership test dropped layout-issue and text-issue outright."""
        assert _is_known_defect_label(label) is True

    @pytest.mark.parametrize("label", ["layout-shift", "text-truncation", "overlay-obstruction", "z-index-issue"])
    def test_raw_taxonomy_labels_are_still_accepted(self, label):
        assert _is_known_defect_label(label) is True

    @pytest.mark.parametrize("label", ["", "insignificant-change", "not-a-real-label"])
    def test_benign_empty_and_unknown_labels_are_rejected(self, label):
        assert _is_known_defect_label(label) is False


class TestGeneratedBenchmarkSuite:
    """The generated suite is the benchmark's contract — guard its shape."""

    @staticmethod
    def _suite_path() -> Path:
        return Path(__file__).resolve().parent.parent / "suites" / "suite.benchmark.yaml"

    def test_suite_exists(self):
        assert self._suite_path().exists(), "run scripts/generate_benchmark_suite.py"

    def test_every_defect_case_compares_against_a_clean_baseline(self):
        for case in load_suite(self._suite_path()):
            if case.name.endswith("-none"):
                continue
            assert case.baseline_url, f"{case.name} has no baseline_url — it would self-compare"
            assert "defect=" in case.url, f"{case.name} does not inject a defect"
            assert "defect=" not in case.baseline_url, f"{case.name} baseline is not clean"
            assert case.baseline_url != case.url, f"{case.name} compares a page against itself"

    def test_control_cases_compare_clean_against_clean(self):
        controls = [c for c in load_suite(self._suite_path()) if c.name.endswith("-none")]
        assert controls, "benchmark has no control group"
        for case in controls:
            assert "defect=" not in case.url
            assert case.baseline_url == case.url
