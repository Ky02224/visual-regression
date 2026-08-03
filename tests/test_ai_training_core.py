"""Tests for ai_training's decision logic — the FYP's core, and its least-tested code.

ai_training.py is 3177 statements. It holds the label taxonomy, the confidence
calibration, the noise suppression that decides whether a detected change is
reported at all, and the metrics that produce every accuracy number in the
report. All of it ran with almost no direct coverage, which means the headline
results rested on code nothing asserted against.

These cover the pure decision functions. Training and inference need a model and
are exercised by the benchmark; these are the parts where a silent wrong answer
changes a published number.
"""

from __future__ import annotations

import numpy as np
import pytest

from visual_regression.ai_training import (
    BENIGN_LABEL_NAME,
    CONSOLIDATED_CLASS_NAMES,
    _build_ai_assessment,
    _compute_multiclass_metrics,
    _consolidate_label,
    _is_micro_rendering_noise,
    _meaningful_change_from_label,
    _optimize_temperature,
    _should_suppress_ai_label,
    calibrate_confidence,
    refine_label_with_dom,
)
from visual_regression.models import CompareResult, DiffRegion


def _result(mismatch=0.0, regions=()):
    return CompareResult(
        baseline_size=[1000, 1000], current_size=[1000, 1000],
        diff_pixels=0, total_pixels=1_000_000, mismatch_pct=mismatch, ssim_score=1.0,
        regions=[DiffRegion(x=0, y=0, width=int(a ** 0.5), height=int(a ** 0.5),
                            area=a, mean_delta=20.0) for a in regions],
    )


# ---------------------------------------------------------------------------
# Label taxonomy
# ---------------------------------------------------------------------------

class TestConsolidateLabel:
    @pytest.mark.parametrize("raw", ["layout-shift", "misaligned-fields", "overlay-obstruction", "z-index-issue"])
    def test_layout_family_folds_to_layout_issue(self, raw):
        assert _consolidate_label(raw) == "layout-issue"

    @pytest.mark.parametrize("raw", ["text-truncation", "unreadable-text"])
    def test_text_family_folds_to_text_issue(self, raw):
        assert _consolidate_label(raw) == "text-issue"

    @pytest.mark.parametrize("raw", ["missing-element", "broken-image", "color-regression", "font-change"])
    def test_standalone_classes_pass_through(self, raw):
        assert _consolidate_label(raw) == raw

    def test_the_benign_sentinel_and_its_alias_agree(self):
        assert _consolidate_label(BENIGN_LABEL_NAME) == "insignificant-change"
        assert _consolidate_label("insignificant-change") == "insignificant-change"

    def test_every_output_is_a_known_class(self):
        """A label that consolidates to something outside the class list would be
        indexed as -1 and silently dropped from training."""
        raw_labels = [
            "layout-shift", "misaligned-fields", "overlay-obstruction", "z-index-issue",
            "text-truncation", "unreadable-text", "missing-element", "broken-image",
            "color-regression", "font-change", BENIGN_LABEL_NAME,
        ]
        for raw in raw_labels:
            assert _consolidate_label(raw) in CONSOLIDATED_CLASS_NAMES, raw

    def test_an_unknown_label_passes_through_unchanged(self):
        assert _consolidate_label("brand-new-mode") == "brand-new-mode"

    def test_consolidation_is_idempotent(self):
        """Applied twice — which happens, since evaluation consolidates a label
        the model already emits in consolidated space."""
        for name in CONSOLIDATED_CLASS_NAMES:
            assert _consolidate_label(_consolidate_label(name)) == _consolidate_label(name)


# ---------------------------------------------------------------------------
# Metrics — every reported accuracy comes through here
# ---------------------------------------------------------------------------

class TestComputeMulticlassMetrics:
    def test_perfect_predictions_score_one(self):
        y = np.array([0, 1, 2, 1, 0])
        m = _compute_multiclass_metrics(y, y, ["a", "b", "c"])
        assert m["accuracy"] == 1.0

    def test_all_wrong_scores_zero(self):
        m = _compute_multiclass_metrics(np.array([0, 0]), np.array([1, 1]), ["a", "b"])
        assert m["accuracy"] == 0.0

    def test_confusion_matrix_rows_are_truth_and_columns_are_prediction(self):
        """Transposing this silently swaps precision and recall in every report."""
        m = _compute_multiclass_metrics(np.array([0]), np.array([1]), ["a", "b"])
        assert m["confusion_matrix"] == [[0, 1], [0, 0]]

    def test_support_counts_the_true_labels(self):
        m = _compute_multiclass_metrics(
            np.array([0, 0, 0, 1]), np.array([0, 0, 1, 1]), ["a", "b"]
        )
        by_label = {c["label"]: c for c in m["per_class"]}
        assert by_label["a"]["support"] == 3
        assert by_label["b"]["support"] == 1

    def test_precision_and_recall_are_computed_per_class(self):
        # class a: 2 correct of 3 true, and 2 of 2 predicted
        m = _compute_multiclass_metrics(
            np.array([0, 0, 0, 1]), np.array([0, 0, 1, 1]), ["a", "b"]
        )
        by_label = {c["label"]: c for c in m["per_class"]}
        assert by_label["a"]["recall"] == pytest.approx(2 / 3, abs=1e-4)
        assert by_label["a"]["precision"] == pytest.approx(1.0)
        assert by_label["b"]["precision"] == pytest.approx(0.5)
        assert by_label["b"]["recall"] == pytest.approx(1.0)

    def test_a_class_with_no_samples_does_not_divide_by_zero(self):
        m = _compute_multiclass_metrics(np.array([0]), np.array([0]), ["a", "b", "c"])
        for entry in m["per_class"]:
            assert entry["precision"] >= 0.0
            assert entry["recall"] >= 0.0

    def test_every_class_appears_even_when_unused(self):
        """A report that silently omits the classes with no samples hides
        exactly the weaknesses worth reporting."""
        m = _compute_multiclass_metrics(np.array([0]), np.array([0]), ["a", "b", "c"])
        assert [c["label"] for c in m["per_class"]] == ["a", "b", "c"]

    def test_matrix_is_square_and_sums_to_the_sample_count(self):
        y_true = np.array([0, 1, 2, 2, 1])
        y_pred = np.array([0, 2, 2, 1, 1])
        m = _compute_multiclass_metrics(y_true, y_pred, ["a", "b", "c"])
        matrix = np.array(m["confusion_matrix"])
        assert matrix.shape == (3, 3)
        assert matrix.sum() == len(y_true)


# ---------------------------------------------------------------------------
# Confidence calibration
# ---------------------------------------------------------------------------

class TestCalibrateConfidence:
    def test_softens_an_overconfident_score(self):
        """Temperature scaling exists to pull extreme scores toward 0.5."""
        out = calibrate_confidence(0.99, "layout-issue")
        assert 0.5 < out["calibrated_score"] < 0.99

    def test_softens_a_confidently_low_score(self):
        out = calibrate_confidence(0.01, "layout-issue")
        assert 0.01 < out["calibrated_score"] < 0.5

    def test_leaves_the_midpoint_alone(self):
        assert calibrate_confidence(0.5, "x")["calibrated_score"] == pytest.approx(0.5, abs=1e-6)

    def test_is_monotonic(self):
        scores = [calibrate_confidence(p, "x")["calibrated_score"] for p in (0.1, 0.3, 0.5, 0.7, 0.9)]
        assert scores == sorted(scores)

    def test_flags_the_uncertain_band(self):
        assert calibrate_confidence(0.5, "x")["low_confidence"] is True

    def test_does_not_flag_a_confident_result(self):
        assert calibrate_confidence(0.999, "x")["low_confidence"] is False
        assert calibrate_confidence(0.001, "x")["low_confidence"] is False

    @pytest.mark.parametrize("extreme", [0.0, 1.0])
    def test_handles_the_probability_bounds_without_a_math_error(self, extreme):
        """log(p/(1-p)) blows up at exactly 0 or 1, which the model can emit."""
        out = calibrate_confidence(extreme, "x")
        assert 0.0 <= out["calibrated_score"] <= 1.0

    def test_a_higher_temperature_softens_more(self):
        mild = calibrate_confidence(0.95, "x", temperature=1.1)["calibrated_score"]
        strong = calibrate_confidence(0.95, "x", temperature=3.0)["calibrated_score"]
        assert strong < mild


class TestOptimizeTemperature:
    def test_returns_a_temperature_in_the_allowed_range(self):
        rng = np.random.default_rng(0)
        logits = rng.normal(size=(50, 3))
        targets = rng.integers(0, 3, size=50)
        assert 0.2 <= _optimize_temperature(logits, targets) <= 3.0

    def test_falls_back_to_the_default_on_bad_input(self):
        """Never raises: this runs at the end of a long training job, and losing
        the run over a calibration hiccup would be absurd."""
        assert _optimize_temperature(np.array([]), np.array([])) == 1.3


# ---------------------------------------------------------------------------
# Noise suppression — decides whether a detection is reported at all
# ---------------------------------------------------------------------------

class TestMicroRenderingNoise:
    def test_a_tiny_change_with_no_regions_is_noise(self):
        assert _is_micro_rendering_noise(_result(mismatch=0.01)) is True

    def test_a_larger_change_with_no_regions_is_not_noise(self):
        assert _is_micro_rendering_noise(_result(mismatch=0.5)) is False

    def test_many_regions_is_never_noise(self):
        """Anti-aliasing shows up in one or two spots, not scattered widely."""
        assert _is_micro_rendering_noise(_result(mismatch=0.01, regions=(10, 10, 10))) is False

    def test_a_large_region_is_never_noise(self):
        assert _is_micro_rendering_noise(_result(mismatch=0.01, regions=(5000,))) is False

    def test_a_high_mismatch_is_never_noise(self):
        assert _is_micro_rendering_noise(_result(mismatch=5.0, regions=(100,))) is False

    def test_a_small_faint_region_is_noise(self):
        assert _is_micro_rendering_noise(_result(mismatch=0.02, regions=(200,))) is True


class TestShouldSuppressAiLabel:
    def _big(self):
        return _result(mismatch=8.0, regions=(50_000,))

    def test_an_empty_label_is_suppressed(self):
        assert _should_suppress_ai_label(self._big(), "", 0.9, 0.5) is True

    @pytest.mark.parametrize("label", ["insignificant-change", "meaningful-change", BENIGN_LABEL_NAME])
    def test_non_defect_labels_are_suppressed(self, label):
        assert _should_suppress_ai_label(self._big(), label, 0.9, 0.5) is True

    def test_a_confident_defect_on_a_big_diff_is_reported(self):
        assert _should_suppress_ai_label(self._big(), "layout-issue", 0.9, 0.5) is False

    def test_a_low_score_is_suppressed(self):
        assert _should_suppress_ai_label(self._big(), "layout-issue", 0.01, 0.5) is True

    def test_micro_noise_is_suppressed_even_with_a_confident_label(self):
        assert _should_suppress_ai_label(_result(mismatch=0.01), "layout-issue", 0.99, 0.5) is True

    def test_a_dom_confirmed_label_survives_the_pixel_heuristics(self):
        """A DOM diff is a structural fact — an element genuinely vanished. Text
        changes routinely produce a pixel delta too small to clear the noise
        floor, and suppressing those discards a confirmed defect."""
        tiny = _result(mismatch=0.01)
        assert _should_suppress_ai_label(tiny, "text-issue", 0.99, 0.5, dom_confirmed=True) is False
        assert _should_suppress_ai_label(tiny, "text-issue", 0.99, 0.5, dom_confirmed=False) is True

    def test_a_dom_confirmed_label_still_needs_a_score(self):
        assert _should_suppress_ai_label(self._big(), "text-issue", 0.001, 0.5, dom_confirmed=True) is True


# ---------------------------------------------------------------------------
# Assessment construction
# ---------------------------------------------------------------------------

class TestMeaningfulChange:
    @pytest.mark.parametrize("label", ["", "insignificant-change", BENIGN_LABEL_NAME, "   "])
    def test_non_defects_are_not_meaningful(self, label):
        assert _meaningful_change_from_label(label) is False

    @pytest.mark.parametrize("label", ["layout-issue", "text-issue", "missing-element", "broken-image"])
    def test_defects_are_meaningful(self, label):
        assert _meaningful_change_from_label(label) is True


class TestBuildAiAssessment:
    def test_preserves_the_model_label_without_simplifying_it(self):
        """Rewriting the label here would decouple inference output from the
        training objective."""
        assessment = _build_ai_assessment(0.87, "layout-issue", 0.5, "visual_ai.pt")
        assert assessment.label == "layout-issue"

    def test_carries_score_threshold_and_model_name(self):
        assessment = _build_ai_assessment(0.123456789, "layout-issue", 0.35, "visual_ai.pt")
        assert assessment.score == pytest.approx(0.123457, abs=1e-6)
        assert assessment.threshold == 0.35
        assert assessment.model_name == "visual_ai.pt"

    def test_derives_meaningful_change_from_the_label(self):
        assert _build_ai_assessment(0.9, "layout-issue", 0.5, "m").meaningful_change is True
        assert _build_ai_assessment(0.9, "insignificant-change", 0.5, "m").meaningful_change is False


# ---------------------------------------------------------------------------
# DOM refinement
# ---------------------------------------------------------------------------

class TestRefineLabelWithDom:
    def test_no_tag_leaves_the_label_alone(self):
        assert refine_label_with_dom("missing-element", None) == "missing-element"

    @pytest.mark.parametrize("tag", ["img", "video", "svg", "canvas", "picture"])
    def test_a_missing_media_element_becomes_broken_image(self, tag):
        assert refine_label_with_dom("missing-element", tag) == "broken-image"

    @pytest.mark.parametrize("tag", ["p", "span", "h1", "label", "li"])
    def test_unreadable_text_on_a_text_tag_becomes_text_issue(self, tag):
        assert refine_label_with_dom("unreadable-text", tag) == "text-issue"

    @pytest.mark.parametrize("tag", ["button", "input", "select", "textarea", "form"])
    def test_a_missed_change_on_a_form_control_becomes_missing_element(self, tag):
        """The visual model calling a vanished form control 'insignificant' is
        the miss this refinement exists to catch."""
        assert refine_label_with_dom("insignificant-change", tag) == "missing-element"

    def test_tags_are_matched_case_insensitively(self):
        assert refine_label_with_dom("missing-element", "IMG") == "broken-image"

    def test_refinement_does_not_fire_for_an_unrelated_label(self):
        """It only sharpens a prediction, never overrides a confident different
        one — layout-issue on an <img> stays layout-issue."""
        assert refine_label_with_dom("layout-issue", "img") == "layout-issue"

    def test_an_unknown_tag_leaves_the_label_alone(self):
        assert refine_label_with_dom("missing-element", "marquee") == "missing-element"
