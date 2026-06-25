"""PASS/FAIL decision logic for pixel, AI, and hybrid comparison modes."""
from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

COMPARISON_MODES = ("pixel", "ai", "hybrid")
DEFAULT_COMPARISON_MODE = "hybrid"


def normalize_comparison_mode(value: str | None, default: str = DEFAULT_COMPARISON_MODE) -> str:
    mode = str(value or default).strip().lower()
    if mode not in COMPARISON_MODES:
        raise ValueError(f"comparison_mode must be one of: {', '.join(COMPARISON_MODES)}")
    return mode


def pixel_would_pass(mismatch_pct: float, threshold_pct: float) -> bool:
    return float(mismatch_pct) <= float(threshold_pct)


def assess_meaningful_change(ai_assessment: Mapping[str, Any] | None) -> bool:
    if not ai_assessment:
        return False
    if "meaningful_change" in ai_assessment:
        return bool(ai_assessment["meaningful_change"])
    label = str(ai_assessment.get("label") or "").strip()
    if not label or label in {"insignificant-change", "meaningful-change", "__benign__"}:
        return False
    score = float(ai_assessment.get("score") or 0.0)
    threshold = float(ai_assessment.get("threshold") or 0.5)
    return score >= threshold


def decide_pass_fail(
    *,
    comparison_mode: str,
    mismatch_pct: float,
    threshold_pct: float,
    ai_assessment: Mapping[str, Any] | None,
    ai_model_available: bool,
) -> Tuple[bool, Dict[str, Any]]:
    mode = normalize_comparison_mode(comparison_mode)
    pixel_pass = pixel_would_pass(mismatch_pct, threshold_pct)
    meaningful = assess_meaningful_change(ai_assessment)
    pixel_fail = not pixel_pass

    if mode == "pixel":
        passed = pixel_pass
        decision_source = "pixel"
    elif mode == "ai":
        if ai_model_available:
            passed = not meaningful
            decision_source = "ai"
        else:
            passed = pixel_pass
            decision_source = "pixel-fallback-no-model"
    else:  # hybrid
        if ai_model_available:
            passed = not (pixel_fail and meaningful)
            decision_source = "hybrid"
        else:
            passed = pixel_pass
            decision_source = "pixel-fallback-no-model"

    return passed, {
        "comparison_mode": mode,
        "decision_source": decision_source,
        "pixel_would_pass": pixel_pass,
        "meaningful_change": meaningful,
    }
