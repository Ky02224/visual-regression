"""Tests for cli.py's pure helpers.

cli.py is 1200 statements at 20% coverage. The command bodies drive browsers and
are covered by the e2e suite, but these helpers are pure and reused by every
other layer — server_services, the dashboard endpoints and the suite runner all
import them — so a change here changes behaviour in places nothing obvious
connects to.

`summarize_severity` in particular is what drives the CI gate: check-ci fails a
build on high/critical severity, so its thresholds decide whether a regression
blocks a merge.
"""

from __future__ import annotations

import pytest

from visual_regression.cli import (
    _baseline_name_from_capture,
    ai_model_is_available,
    _initial_decision_status,
    _slug_part,
    build_ai_explanation,
    now_stamp,
    now_stamp_precise,
    parse_headers,
    parse_viewport,
    resolve_ai_model_path,
    summarize_severity,
)
from visual_regression.config import WorkspacePaths
from visual_regression.models import CompareResult, DiffRegion


# ---------------------------------------------------------------------------
# parse_viewport
# ---------------------------------------------------------------------------

class TestParseViewport:
    def test_parses_a_well_formed_value(self):
        assert parse_viewport("1440x900") == (1440, 900)

    def test_is_case_insensitive(self):
        assert parse_viewport("1440X900") == (1440, 900)

    @pytest.mark.parametrize("raw", ["1440", "1440x900x1", "", "x"])
    def test_rejects_a_malformed_shape(self, raw):
        with pytest.raises(ValueError):
            parse_viewport(raw)

    @pytest.mark.parametrize("raw", ["0x900", "1440x0", "-100x900"])
    def test_rejects_non_positive_dimensions(self, raw):
        """A zero-width viewport produces a zero-byte screenshot that then fails
        far away from here, in the image comparison."""
        with pytest.raises(ValueError, match="must be > 0"):
            parse_viewport(raw)

    def test_rejects_non_numeric_dimensions(self):
        with pytest.raises(ValueError):
            parse_viewport("widexhigh")


# ---------------------------------------------------------------------------
# parse_headers
# ---------------------------------------------------------------------------

class TestParseHeaders:
    def test_parses_a_single_header(self):
        assert parse_headers(["Accept: application/json"]) == {"Accept": "application/json"}

    def test_strips_surrounding_whitespace(self):
        assert parse_headers(["  X-Key  :  value  "]) == {"X-Key": "value"}

    def test_keeps_colons_inside_the_value(self):
        """Authorization and URL values legitimately contain colons."""
        assert parse_headers(["Referer: https://example.com:8443/x"]) == {
            "Referer": "https://example.com:8443/x"
        }

    def test_parses_several_headers(self):
        assert parse_headers(["A: 1", "B: 2"]) == {"A": "1", "B": "2"}

    def test_later_duplicate_wins(self):
        assert parse_headers(["A: 1", "A: 2"]) == {"A": "2"}

    def test_empty_input_gives_no_headers(self):
        assert parse_headers([]) == {}

    def test_rejects_a_header_without_a_colon(self):
        with pytest.raises(ValueError, match="Use Header:Value"):
            parse_headers(["NotAHeader"])


# ---------------------------------------------------------------------------
# summarize_severity — drives the CI gate
# ---------------------------------------------------------------------------

class TestSummarizeSeverity:
    def test_a_clean_run_is_low(self):
        assert summarize_severity(0.0, 0, None)["label"] == "low"

    def test_a_large_mismatch_across_many_regions_is_high(self):
        assert summarize_severity(10.0, 10, 0.9)["label"] == "high"

    @pytest.mark.parametrize("label", ["low", "medium", "high"])
    def test_label_is_always_one_of_the_three(self, label):
        results = {summarize_severity(m, r, s)["label"]
                   for m in (0.0, 1.0, 5.0, 20.0)
                   for r in (0, 4, 12)
                   for s in (None, 0.3, 0.7, 0.95)}
        assert results <= {"low", "medium", "high"}

    def test_severity_is_monotonic_in_mismatch(self):
        scores = [summarize_severity(m, 0, None)["score"] for m in (0.1, 0.6, 3.0, 9.0)]
        assert scores == sorted(scores)

    def test_severity_is_monotonic_in_region_count(self):
        scores = [summarize_severity(0.0, r, None)["score"] for r in (0, 3, 8)]
        assert scores == sorted(scores)

    def test_severity_is_monotonic_in_ai_confidence(self):
        scores = [summarize_severity(0.0, 0, s)["score"] for s in (0.1, 0.7, 0.9)]
        assert scores == sorted(scores)

    def test_a_missing_ai_score_does_not_contribute(self):
        assert summarize_severity(1.0, 2, None)["score"] == summarize_severity(1.0, 2, 0.0)["score"]

    @pytest.mark.parametrize("label", [
        "missing-element", "layout-shift", "text-truncation", "broken-image",
        "misaligned-fields", "layout-issue", "text-issue",
    ])
    def test_structural_labels_weigh_more_than_cosmetic_ones(self, label):
        structural = summarize_severity(0.0, 0, None, label)["score"]
        cosmetic = summarize_severity(0.0, 0, None, "color-regression")["score"]
        assert structural > cosmetic

    def test_an_unknown_label_adds_nothing(self):
        assert summarize_severity(1.0, 1, 0.5, "not-a-label")["score"] == \
               summarize_severity(1.0, 1, 0.5, None)["score"]

    def test_consolidated_labels_are_recognised(self):
        """layout-issue and text-issue are what the current model emits; if the
        table only knew the older raw names, every modern run would be scored as
        if it had no label at all."""
        for label in ("layout-issue", "text-issue"):
            assert summarize_severity(0.0, 0, None, label)["score"] > 0


# ---------------------------------------------------------------------------
# build_ai_explanation
# ---------------------------------------------------------------------------

def _result(mismatch=0.0, regions=0, area=100):
    return CompareResult(
        baseline_size=[100, 100], current_size=[100, 100],
        diff_pixels=0, total_pixels=10000, mismatch_pct=mismatch, ssim_score=1.0,
        regions=[DiffRegion(x=0, y=0, width=10, height=10, area=area, mean_delta=5.0)
                 for _ in range(regions)],
    )


class TestBuildAiExplanation:
    def test_prefers_an_llm_supplied_explanation(self):
        text = build_ai_explanation(_result(), {"ai_explanation": "Custom narrative."})
        assert text == "Custom narrative."

    def test_says_so_when_no_label_was_assigned(self):
        assert "did not assign" in build_ai_explanation(_result(), {})

    def test_describes_a_known_label(self):
        text = build_ai_explanation(_result(), {"label": "missing-element"})
        assert "missing" in text.lower()

    def test_falls_back_for_an_unrecognised_label(self):
        text = build_ai_explanation(_result(), {"label": "brand-new-label"})
        assert "visual change assessment" in text

    def test_reports_an_elevated_mismatch(self):
        assert "elevated" in build_ai_explanation(_result(mismatch=9.0), {"label": "layout-issue"})

    def test_reports_a_measurable_mismatch(self):
        assert "measurable" in build_ai_explanation(_result(mismatch=2.0), {"label": "layout-issue"})

    def test_mentions_the_region_count(self):
        assert "6 changed regions" in build_ai_explanation(_result(regions=6), {"label": "layout-issue"})

    def test_mentions_a_large_changed_area(self):
        text = build_ai_explanation(_result(regions=1, area=50000), {"label": "layout-issue"})
        assert "50000 pixels" in text

    def test_notes_when_rule_fusion_promoted_the_label(self):
        """The score is below threshold yet a label was still assigned — the
        report should explain why rather than look self-contradictory."""
        text = build_ai_explanation(_result(), {"label": "layout-issue", "score": 0.2, "threshold": 0.5})
        assert "Rule fusion" in text

    def test_never_returns_an_empty_string(self):
        assert build_ai_explanation(_result(), {}).strip()


# ---------------------------------------------------------------------------
# Name slugging
# ---------------------------------------------------------------------------

class TestSlugging:
    def test_uses_the_fallback_for_an_empty_value(self):
        assert _slug_part(None, "desktop") == "desktop"
        assert _slug_part("   ", "desktop") == "desktop"

    def test_dots_become_hyphens(self):
        """Dots in a path segment would otherwise read as a file extension."""
        assert "." not in _slug_part("iPhone 13.2", "desktop")

    def test_baseline_name_includes_host_browser_device_and_locale(self):
        name = _baseline_name_from_capture(
            "https://example.com/products/list", "chromium", "iPhone 13", "zh-CN"
        )
        assert "example.com" in name
        assert "products_list" in name
        assert "chromium" in name
        assert "zh-CN" in name

    def test_root_path_becomes_home(self):
        assert "home" in _baseline_name_from_capture("https://example.com/", "chromium", None, None)

    def test_port_is_kept_but_not_as_a_colon(self):
        name = _baseline_name_from_capture("http://127.0.0.1:8130/demo", "chromium", None, None)
        assert ":" not in name
        assert "8130" in name

    def test_locales_produce_distinct_baselines(self):
        """Same page in two languages must not share one baseline."""
        en = _baseline_name_from_capture("https://example.com/", "chromium", None, "en-US")
        zh = _baseline_name_from_capture("https://example.com/", "chromium", None, "zh-CN")
        assert en != zh

    def test_devices_produce_distinct_baselines(self):
        desktop = _baseline_name_from_capture("https://example.com/", "chromium", None, "en-US")
        mobile = _baseline_name_from_capture("https://example.com/", "chromium", "iPhone 13", "en-US")
        assert desktop != mobile


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

class TestDecisionStatus:
    def test_a_pass_is_auto_passed_with_a_timestamp(self):
        status = _initial_decision_status(True)
        assert status["status"] == "auto-pass"
        assert status["timestamp"]

    def test_a_failure_waits_for_a_human(self):
        """A failing run must not carry a timestamp that makes it look reviewed."""
        status = _initial_decision_status(False)
        assert status["status"] == "pending"
        assert "timestamp" not in status


class TestAiModelIsAvailable:
    """A model counts as available in any format the loader can actually read.

    This asked `model_path.exists()` before, which is the wrong question. The
    path is a BASE name — visual_ai.pt — from which the loader derives the
    sidecars it really opens (.torchscript.pt, .quant.onnx + .json, then the
    checkpoint). A deployment carrying only the ONNX export and its metadata,
    which is exactly what CI restores because the 124MB checkpoint is too large
    to version, was reported as having no model at all. Every comparison then
    degraded to pixel-only and recorded decision_source
    "pixel-fallback-no-model" — a silent downgrade, not an error.
    """

    def test_no_path_is_not_available(self):
        assert ai_model_is_available(None) is False

    def test_an_empty_directory_is_not_available(self, tmp_path):
        assert ai_model_is_available(tmp_path / "visual_ai.pt") is False

    def test_a_checkpoint_alone_is_available(self, tmp_path):
        (tmp_path / "visual_ai.pt").write_bytes(b"weights")
        assert ai_model_is_available(tmp_path / "visual_ai.pt") is True

    def test_a_torchscript_export_alone_is_available(self, tmp_path):
        (tmp_path / "visual_ai.torchscript.pt").write_bytes(b"ts")
        assert ai_model_is_available(tmp_path / "visual_ai.pt") is True

    def test_a_quantised_onnx_with_metadata_is_available(self, tmp_path):
        """The CI case: 32MB ONNX plus a 3KB sidecar, no checkpoint."""
        (tmp_path / "visual_ai.quant.onnx").write_bytes(b"onnx")
        (tmp_path / "visual_ai.json").write_text("{}", encoding="utf-8")
        assert ai_model_is_available(tmp_path / "visual_ai.pt") is True

    def test_a_standard_onnx_with_metadata_is_available(self, tmp_path):
        (tmp_path / "visual_ai.onnx").write_bytes(b"onnx")
        (tmp_path / "visual_ai.json").write_text("{}", encoding="utf-8")
        assert ai_model_is_available(tmp_path / "visual_ai.pt") is True

    def test_an_onnx_without_metadata_is_not_available(self, tmp_path):
        """class_names, threshold and image_size all come from the sidecar, so
        the ONNX alone cannot be loaded — claiming otherwise would swap a clean
        fallback for an inference-time crash."""
        (tmp_path / "visual_ai.quant.onnx").write_bytes(b"onnx")
        assert ai_model_is_available(tmp_path / "visual_ai.pt") is False

    def test_metadata_without_any_weights_is_not_available(self, tmp_path):
        (tmp_path / "visual_ai.json").write_text("{}", encoding="utf-8")
        assert ai_model_is_available(tmp_path / "visual_ai.pt") is False


class TestResolveAiModelPath:
    def test_no_ai_wins_over_an_explicit_path(self, tmp_path):
        assert resolve_ai_model_path(WorkspacePaths(tmp_path), str(tmp_path / "m.pt"), True) is None

    def test_an_explicit_path_is_returned_as_given(self, tmp_path):
        assert resolve_ai_model_path(WorkspacePaths(tmp_path), "/models/custom.pt", False).name == "custom.pt"

    def test_returns_none_when_no_default_model_exists(self, tmp_path):
        """This is the CI path: without a model the caller degrades to pixel
        comparison rather than failing."""
        paths = WorkspacePaths(tmp_path / ".visual-regression")
        paths.ensure()
        assert resolve_ai_model_path(paths, None, False) is None

    def test_finds_the_default_model_when_present(self, tmp_path):
        paths = WorkspacePaths(tmp_path / ".visual-regression")
        paths.ensure()
        (paths.models_dir / "visual_ai.pt").write_bytes(b"weights")
        assert resolve_ai_model_path(paths, None, False).name == "visual_ai.pt"


class TestTimestamps:
    def test_stamp_is_sortable_and_fixed_width(self):
        assert len(now_stamp()) == len("20260803-120000")

    def test_precise_stamp_adds_microseconds(self):
        assert len(now_stamp_precise()) > len(now_stamp())

    def test_precise_stamps_differ_between_calls(self):
        """Run directory names are built from this; a collision would overwrite
        another run's artifacts."""
        assert len({now_stamp_precise() for _ in range(50)}) > 1
