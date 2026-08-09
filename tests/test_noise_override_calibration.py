"""The confidence at which the model outranks the pixel-noise rules is measured
per model, not hard-coded.

_NOISE_OVERRIDE_CONFIDENCE (0.80) was read off one model: unchanged pages topped
out at 0.729 there, real low-delta defects sat at 0.779. A model trained on the
corrected data peaked at 0.756 across 286 real defects — all of them under 0.80,
so the exemption never fired once and the noise rules discarded 129 genuine
defects, 36.9% of the exam, every one reported as "no change". The 0.80 bought
nothing in exchange: the benign pages in that run scored 0.000, because a page
with no diff regions never reaches the model at all.

So the threshold is derived from the benign validation samples of whichever
model is being trained, published in the checkpoint, and read back at inference.
Checkpoints without it keep the old constant.
"""
import numpy as np
import pytest

from visual_regression.ai_training import (
    _NOISE_OVERRIDE_CONFIDENCE,
    _calibrate_noise_override,
    _should_suppress_ai_label,
)
from visual_regression.models import CompareResult

CLASSES = ["insignificant-change", "color-regression", "missing-element", "layout-issue"]


def logits_for(confidences, klass):
    """Logits whose softmax peak sits at each requested confidence."""
    rows = []
    for c in confidences:
        row = np.zeros(len(CLASSES), dtype=np.float64)
        # softmax of [x, 0, 0, 0] peaks at e^x / (e^x + 3)
        rest = len(CLASSES) - 1
        row[klass] = float(np.log(c * rest / max(1.0 - c, 1e-9)))
        rows.append(row)
    return np.stack(rows)


def low_delta_result():
    """The shape of change that the noise rules exist to discard."""
    return CompareResult(baseline_size=[800, 600], current_size=[800, 600],
                         diff_pixels=240, total_pixels=480000, mismatch_pct=0.05,
                         ssim_score=0.999, regions=[])


class TestCalibration:
    def test_it_reads_the_ceiling_off_the_benign_samples(self):
        benign = logits_for([0.30] * 60, 0)
        targets = np.zeros(60, dtype=np.int64)

        got = _calibrate_noise_override(benign, targets, CLASSES, temperature=1.0)

        assert 0.30 < got < 0.40, got

    def test_a_model_with_low_confidences_gets_a_low_threshold(self):
        """The failure this was built for: every real defect below 0.80."""
        benign = logits_for([0.26] * 60, 0)
        targets = np.zeros(60, dtype=np.int64)

        got = _calibrate_noise_override(benign, targets, CLASSES, temperature=1.0)

        assert got < 0.756, "a defect at the observed 0.756 peak must be able to clear this"

    def test_too_few_benign_samples_keeps_the_hand_set_value(self):
        """Ten points cannot locate a 99th percentile; inventing one from them
        would be worse than the constant it replaces."""
        benign = logits_for([0.30] * 10, 0)

        got = _calibrate_noise_override(benign, np.zeros(10, dtype=np.int64), CLASSES, 1.0)

        assert got == _NOISE_OVERRIDE_CONFIDENCE

    def test_it_is_capped_so_a_degenerate_split_cannot_suppress_everything(self):
        benign = logits_for([0.999] * 60, 0)

        got = _calibrate_noise_override(benign, np.zeros(60, dtype=np.int64), CLASSES, 1.0)

        assert got <= 0.90

    def test_it_has_a_floor_so_noise_is_still_filtered(self):
        benign = logits_for([0.001] * 60, 0)

        got = _calibrate_noise_override(benign, np.zeros(60, dtype=np.int64), CLASSES, 1.0)

        assert got >= 0.20

    def test_only_benign_samples_set_the_ceiling(self):
        """Defect confidences must not raise the bar that defects have to clear."""
        benign = logits_for([0.30] * 60, 0)
        defects = logits_for([0.85] * 60, 1)
        logits = np.concatenate([benign, defects])
        targets = np.concatenate([np.zeros(60, dtype=np.int64), np.ones(60, dtype=np.int64)])

        got = _calibrate_noise_override(logits, targets, CLASSES, temperature=1.0)

        assert got < 0.50, got


class TestSuppressionUsesIt:
    def test_a_low_delta_verdict_survives_when_it_clears_the_model_s_own_ceiling(self):
        suppressed = _should_suppress_ai_label(
            low_delta_result(), "color-regression", score=0.60, threshold=0.35,
            noise_override=0.35,
        )

        assert not suppressed

    def test_the_same_verdict_is_discarded_under_the_hand_set_constant(self):
        """Exactly the regression that cost 129 defects."""
        suppressed = _should_suppress_ai_label(
            low_delta_result(), "color-regression", score=0.60, threshold=0.35,
        )

        assert suppressed

    def test_noise_below_the_calibrated_ceiling_is_still_discarded(self):
        suppressed = _should_suppress_ai_label(
            low_delta_result(), "color-regression", score=0.25, threshold=0.35,
            noise_override=0.35,
        )

        assert suppressed

    @pytest.mark.parametrize("label", ["insignificant-change", "meaningful-change", ""])
    def test_non_verdicts_are_unaffected(self, label):
        assert _should_suppress_ai_label(low_delta_result(), label, 0.99, 0.35,
                                         noise_override=0.20)
