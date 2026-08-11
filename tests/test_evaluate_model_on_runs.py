"""evaluate_model_on_runs used to score model predictions against the wrong
class-index space: ground truth (sample.label_index) is drawn from the
7-class CONSOLIDATED_CLASS_NAMES the model is actually trained on, but
predictions were indexed via dataset_generator.DEFECT_LABEL_TO_INDEX — a
disjoint ~10-class raw synthetic-defect-mode taxonomy that doesn't even
contain most consolidated label strings ("layout-issue", "text-issue",
"insignificant-change" aren't keys in it at all). Every prediction of one of
those three labels silently fell back to index 0 ("missing-element"), and
even labels that happen to share a literal string ("missing-element",
"broken-image", "color-regression", "font-change") landed at a different
numeric index in each list — so the confusion matrix / precision / recall in
every ai-run-eval-*.json report was scored against nonsense, without ever
raising an error.
"""
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from visual_regression.ai_training import PairSample, CONSOLIDATED_CLASS_NAMES, evaluate_model_on_runs
from visual_regression.config import WorkspacePaths
from visual_regression.models import AIAssessment


def _fake_sample(label_name: str) -> PairSample:
    label_index = CONSOLIDATED_CLASS_NAMES.index(label_name)
    img = np.zeros((32, 32, 3), dtype=np.uint8)
    return PairSample(baseline_rgb=img, current_rgb=img, rule_features=np.zeros(9), label_index=label_index, label_name=label_name)


@pytest.fixture
def paths(tmp_path):
    p = WorkspacePaths(root=tmp_path / ".visual-regression")
    p.ensure()
    return p


def test_perfect_predictions_score_as_perfect(paths):
    """Ground truth and predicted label are the same consolidated label for
    every sample — a real model with 100% accuracy on this set. Before the
    fix, this could still show near-zero precision/recall for several
    classes purely from the index-space mismatch."""
    samples = [
        # Not layout-issue: that label was folded into missing-element on
        # 2026-08-11 (see _consolidate_label), so it can no longer appear as
        # its own bucket in the per-class breakdown this test inspects.
        _fake_sample("broken-image"),
        _fake_sample("broken-image"),
        _fake_sample("insignificant-change"),
        _fake_sample("text-issue"),
    ]

    def fake_assess_result(result, model_path, **kwargs):
        # Mirror whichever ground-truth sample is currently being scored via
        # a call counter closed over the test, so "predicted" == "actual".
        idx = fake_assess_result.call_count
        fake_assess_result.call_count += 1
        label = samples[idx].label_name
        return AIAssessment(score=0.9, label=label, threshold=0.5, model_name="fake")
    fake_assess_result.call_count = 0

    with patch("visual_regression.ai_training._load_run_pair_samples", return_value=samples), \
         patch("visual_regression.ai_training.compare_arrays", return_value=(object(), None, None)), \
         patch("visual_regression.ai_training._write_temp_eval_image"), \
         patch("visual_regression.ai_training.assess_result", side_effect=fake_assess_result):
        payload = evaluate_model_on_runs(paths, Path("fake-model.pt"))

    assert payload["class_names"] == CONSOLIDATED_CLASS_NAMES
    per_class = {c["label"]: c for c in payload["evaluation"]["per_class"]}
    # Every ground-truth label present was also the (correct) prediction —
    # precision and recall for those classes must be 1.0, not scattered
    # across the wrong indices.
    assert per_class["broken-image"]["precision"] == 1.0
    assert per_class["broken-image"]["recall"] == 1.0
    assert per_class["insignificant-change"]["recall"] == 1.0
    assert per_class["text-issue"]["recall"] == 1.0
