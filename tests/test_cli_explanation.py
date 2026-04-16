from visual_regression.cli import build_ai_explanation
from visual_regression.models import CompareResult, DiffRegion


def test_build_ai_explanation_humanized_for_missing_element():
    result = CompareResult(
        baseline_size=[1440, 900],
        current_size=[1440, 900],
        diff_pixels=1200,
        total_pixels=1296000,
        mismatch_pct=6.2,
        ssim_score=0.91,
        regions=[DiffRegion(x=20, y=30, width=200, height=80, area=16000, mean_delta=25.0)],
    )
    explanation = build_ai_explanation(
        result,
        {
            "label": "missing-element",
            "score": 0.74,
            "threshold": 0.35,
        },
    )

    assert "missing" in explanation.lower()
    assert "Mismatch is elevated" in explanation
    assert "AI confidence score" in explanation


def test_build_ai_explanation_mentions_rule_fusion_when_needed():
    result = CompareResult(
        baseline_size=[1440, 900],
        current_size=[1440, 900],
        diff_pixels=800,
        total_pixels=1296000,
        mismatch_pct=1.4,
        ssim_score=0.95,
        regions=[DiffRegion(x=40, y=30, width=180, height=30, area=5400, mean_delta=18.0)],
    )
    explanation = build_ai_explanation(
        result,
        {
            "label": "text-truncation",
            "score": 0.21,
            "threshold": 0.35,
        },
    )

    assert "text" in explanation.lower()
    assert "Rule fusion promoted" in explanation
