"""Tests for the summarize_severity() function in cli.py.

Covers the high / medium / low severity boundaries, including
AI score and AI label contributions to the final score.
"""
from __future__ import annotations

import pytest

from visual_regression.cli import summarize_severity


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _severity(
    mismatch_pct: float = 0.0,
    diff_regions: int = 0,
    ai_score: float | None = None,
    ai_label: str | None = None,
) -> dict:
    return summarize_severity(mismatch_pct, diff_regions, ai_score, ai_label)


# ---------------------------------------------------------------------------
# Mismatch percentage thresholds
# ---------------------------------------------------------------------------

class TestMismatchThresholds:
    def test_zero_mismatch_gives_low(self):
        result = _severity(mismatch_pct=0.0)
        assert result["label"] == "low"
        assert result["score"] == 0

    def test_below_0_5_gives_zero_pixel_score(self):
        result = _severity(mismatch_pct=0.4)
        assert result["score"] == 0

    def test_at_0_5_gives_score_1(self):
        result = _severity(mismatch_pct=0.5)
        assert result["score"] >= 1

    def test_at_2_gives_score_2(self):
        result = _severity(mismatch_pct=2.0)
        assert result["score"] >= 2

    def test_at_8_gives_score_3(self):
        result = _severity(mismatch_pct=8.0)
        assert result["score"] >= 3

    def test_above_8_still_caps_at_3_pixel_points(self):
        r1 = _severity(mismatch_pct=8.0)
        r2 = _severity(mismatch_pct=50.0)
        # pixel contribution should be the same (3 points) for both
        assert r1["score"] == r2["score"]


# ---------------------------------------------------------------------------
# Diff region count thresholds
# ---------------------------------------------------------------------------

class TestDiffRegionThresholds:
    def test_zero_regions_gives_no_region_score(self):
        assert _severity(diff_regions=0)["score"] == 0

    def test_2_regions_gives_no_region_score(self):
        assert _severity(diff_regions=2)["score"] == 0

    def test_3_regions_gives_score_1(self):
        assert _severity(diff_regions=3)["score"] >= 1

    def test_8_regions_gives_score_2(self):
        result = _severity(diff_regions=8)
        assert result["score"] >= 2


# ---------------------------------------------------------------------------
# AI score contribution
# ---------------------------------------------------------------------------

class TestAIScoreContribution:
    def test_no_ai_score_gives_no_ai_contribution(self):
        baseline = _severity(mismatch_pct=1.0)["score"]
        with_ai_none = _severity(mismatch_pct=1.0, ai_score=None)["score"]
        assert baseline == with_ai_none

    def test_low_ai_score_gives_no_contribution(self):
        s_without = _severity(mismatch_pct=1.0)["score"]
        s_with = _severity(mismatch_pct=1.0, ai_score=0.59)["score"]
        assert s_without == s_with

    def test_ai_score_0_6_gives_plus_1(self):
        s_without = _severity(mismatch_pct=1.0)["score"]
        s_with = _severity(mismatch_pct=1.0, ai_score=0.6)["score"]
        assert s_with == s_without + 1

    def test_ai_score_0_85_gives_plus_2(self):
        s_without = _severity(mismatch_pct=1.0)["score"]
        s_with = _severity(mismatch_pct=1.0, ai_score=0.85)["score"]
        assert s_with == s_without + 2


# ---------------------------------------------------------------------------
# AI label contribution
# ---------------------------------------------------------------------------

class TestAILabelContribution:
    HIGH_IMPACT_LABELS = [
        "missing-element",
        "layout-shift",
        "text-truncation",
        "broken-image",
        "misaligned-fields",
    ]
    LOW_IMPACT_LABELS = [
        "color-regression",
        "overlay-obstruction",
        "unreadable-text",
    ]

    @pytest.mark.parametrize("label", HIGH_IMPACT_LABELS)
    def test_high_impact_labels_give_plus_2(self, label: str):
        s_without = _severity()["score"]
        s_with = _severity(ai_label=label)["score"]
        assert s_with == s_without + 2

    @pytest.mark.parametrize("label", LOW_IMPACT_LABELS)
    def test_low_impact_labels_give_plus_1(self, label: str):
        s_without = _severity()["score"]
        s_with = _severity(ai_label=label)["score"]
        assert s_with == s_without + 1

    def test_unknown_label_gives_no_contribution(self):
        s_without = _severity()["score"]
        s_with = _severity(ai_label="unknown-defect")["score"]
        assert s_with == s_without


# ---------------------------------------------------------------------------
# Final severity label thresholds
# ---------------------------------------------------------------------------

class TestFinalLabel:
    def test_score_0_to_2_is_low(self):
        result = _severity(mismatch_pct=0.0, diff_regions=0)
        assert result["label"] == "low"

    def test_score_3_is_medium(self):
        # mismatch>=2 (score+2) + regions>=3 (score+1) = 3 → medium
        result = _severity(mismatch_pct=2.0, diff_regions=3)
        assert result["label"] == "medium"
        assert result["score"] == 3

    def test_score_5_is_high(self):
        # mismatch>=8 (3) + ai_score>=0.85 (2) = 5 → high
        result = _severity(mismatch_pct=8.0, ai_score=0.85)
        assert result["label"] == "high"
        assert result["score"] >= 5

    def test_combined_all_max_is_high(self):
        result = _severity(
            mismatch_pct=10.0,
            diff_regions=10,
            ai_score=0.95,
            ai_label="layout-shift",
        )
        assert result["label"] == "high"
        assert result["score"] >= 5
