"""The rule-feature vector must reach the model at the width it was built for.

Feature blocks are appended over time (9 pixel features, then 38 DOM aggregates,
then 14 structural ones), so a model exported before a block existed takes a
narrower input than the current code produces. Every inference path therefore
has to fit the vector to the model rather than to `FULL_FEATURE_NAMES`.

Getting this wrong does not raise anything a caller sees: `assess_results_batch`
catches the resulting shape error and silently drops the whole batch to
one-by-one inference, and `assess_result` catches it and drops to the rule-only
fallback. The score still comes out, just not from the model that was supposed
to produce it — which is why these need explicit tests.
"""
import numpy as np
import pytest

from visual_regression.ai_features import FULL_FEATURE_NAMES, RULE_FEATURE_NAMES
from visual_regression.ai_training import _fit_rule_vector, assess_results_batch
from visual_regression.models import CompareResult

torch = pytest.importorskip("torch")

LEGACY_RULE_DIM = len(RULE_FEATURE_NAMES)  # 9 — before DOM/struct blocks existed
EMB_DIM = 4


def _write_image(path, value):
    import cv2
    cv2.imwrite(str(path), np.full((40, 40, 3), value, dtype=np.uint8))
    return path


def _result():
    return CompareResult(
        baseline_size=[40, 40], current_size=[40, 40],
        diff_pixels=100, total_pixels=1600, mismatch_pct=6.25,
        ssim_score=0.8, regions=[],
    )


class _StubBackbone(torch.nn.Module):
    """Emits a fixed-width embedding without downloading ResNet50 weights."""

    def __init__(self):
        super().__init__()
        self.linear = torch.nn.Linear(3, EMB_DIM)

    def forward(self, x):
        return self.linear(x.mean(dim=(2, 3)))

    def to(self, *args, **kwargs):
        return self


def _legacy_loaded_model():
    """A hybrid model frozen at the 9-wide rule input, three embedding streams."""
    head = torch.nn.Linear((EMB_DIM * 3) + LEGACY_RULE_DIM, 2)
    head.eval()
    return {
        "type": "hybrid-multiclass",
        "torch": torch,
        "backbone": _StubBackbone().eval(),
        "head": head,
        "threshold": 0.5,
        "image_size": 32,
        "model_type": "resnet50-siamese-rule-fusion-multiclass",
        "class_names": ["layout-issue", "broken-image"],
        "calibrated_temperature": 1.3,
        "rule_dim": LEGACY_RULE_DIM,
        "embedding_dim": EMB_DIM,
        "num_streams": 3,
    }


def test_fit_rule_vector_truncates_to_a_narrower_model():
    parts = [np.ones(LEGACY_RULE_DIM), np.ones(38) * 2, np.ones(14) * 3]
    fitted = _fit_rule_vector(parts, LEGACY_RULE_DIM)
    assert fitted.shape == (LEGACY_RULE_DIM,)
    # Feature order is append-only, so the retained block is the leading one.
    assert np.all(fitted == 1)


def test_fit_rule_vector_pads_for_a_wider_model():
    fitted = _fit_rule_vector([np.ones(LEGACY_RULE_DIM)], len(FULL_FEATURE_NAMES))
    assert fitted.shape == (len(FULL_FEATURE_NAMES),)
    assert np.all(fitted[LEGACY_RULE_DIM:] == 0)


def test_batch_inference_reaches_a_model_narrower_than_the_current_features(
    tmp_path, monkeypatch
):
    """The batch path stacked its fitted rows and then padded them back up to
    len(FULL_FEATURE_NAMES), handing a 9-input head a 48-wide vector. torch.cat
    produced a width the head could not accept and the whole batch fell through
    to the sequential fallback — with no error surfaced anywhere.
    """
    monkeypatch.setattr(
        "visual_regression.ai_training._load_legacy_or_hybrid_model",
        lambda p: _legacy_loaded_model(),
    )

    def _fallback_is_a_failure(results_list, model_path):
        raise AssertionError(
            "batch inference fell back to one-by-one — the rule vector did not "
            "match the width the head was built for"
        )

    monkeypatch.setattr(
        "visual_regression.ai_training._assess_results_batch_fallback",
        _fallback_is_a_failure,
    )

    items = [
        {
            "result": _result(),
            "baseline_image_path": _write_image(tmp_path / f"bl{i}.png", 10),
            "current_image_path": _write_image(tmp_path / f"cu{i}.png", 200),
        }
        for i in range(3)
    ]

    assessments = assess_results_batch(items, tmp_path / "visual_ai.pt", device="cpu")

    assert len(assessments) == 3
    for entry in assessments:
        assert entry["label"] in {"layout-issue", "broken-image", ""}
        assert "error" not in entry


def test_batch_inference_still_works_at_the_current_full_width(tmp_path, monkeypatch):
    """The counterpart: a head built for the full 48 must receive all 48, not a
    truncated vector. Fitting to the model has to work in both directions.
    """
    loaded = _legacy_loaded_model()
    loaded["head"] = torch.nn.Linear((EMB_DIM * 3) + len(FULL_FEATURE_NAMES), 2).eval()
    loaded["rule_dim"] = len(FULL_FEATURE_NAMES)
    monkeypatch.setattr(
        "visual_regression.ai_training._load_legacy_or_hybrid_model", lambda p: loaded)
    monkeypatch.setattr(
        "visual_regression.ai_training._assess_results_batch_fallback",
        lambda results_list, model_path: pytest.fail("fell back at full width"),
    )

    items = [{
        "result": _result(),
        "baseline_image_path": _write_image(tmp_path / "bl.png", 10),
        "current_image_path": _write_image(tmp_path / "cu.png", 200),
    }]

    assert len(assess_results_batch(items, tmp_path / "visual_ai.pt", device="cpu")) == 1
