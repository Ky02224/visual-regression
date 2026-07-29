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
    # "meaningful-change" is the legacy/binary model's positive label (see
    # ai_training.py's _meaningful_change_from_label, the canonical version
    # of this same fallback) — it must not be treated as "not meaningful".
    if not label or label in {"insignificant-change", "__benign__"}:
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
    ai_error: bool = False,
) -> Tuple[bool, Dict[str, Any]]:
    """Combine pixel and AI signals into a pass/fail decision.

    ``ai_error`` must be set whenever the AI model was expected to run
    (``ai_model_available`` is True) but the inference call itself raised —
    e.g. a corrupt model file, a missing dependency, or a crashed inference
    service. Without this flag, a failed AI call produces an empty
    ``ai_assessment``, which `assess_meaningful_change` reads as "no
    meaningful change" — in "ai"/"hybrid" mode that silently auto-passes the
    build under a decision_source that still claims "ai"/"hybrid", even
    though the AI never actually rendered a verdict. When ``ai_error`` is
    True the decision is forced to fall back to the pixel-only result, and
    ``decision_source`` is tagged distinctly from the "no model configured"
    fallback so the failure is visible in reports/logs.
    """
    mode = normalize_comparison_mode(comparison_mode)
    pixel_pass = pixel_would_pass(mismatch_pct, threshold_pct)
    meaningful = assess_meaningful_change(ai_assessment)
    pixel_fail = not pixel_pass
    effective_ai_available = ai_model_available and not ai_error

    if mode == "pixel":
        passed = pixel_pass
        decision_source = "pixel"
    elif mode == "ai":
        if effective_ai_available:
            passed = not meaningful
            decision_source = "ai"
        else:
            passed = pixel_pass
            decision_source = "pixel-fallback-ai-error" if ai_error else "pixel-fallback-no-model"
    else:  # hybrid
        if effective_ai_available:
            # Requiring BOTH pixel_fail and meaningful is a deliberate
            # precision-over-recall choice for the common case: the raw CNN
            # score is a probabilistic guess, and gating it behind pixel
            # corroboration avoids nagging developers with false-positive
            # FAILs from an imperfect model. But a DOM-diff-confirmed
            # verdict isn't a guess — diagnose_from_dom_diff() compares
            # actual before/after element structure and only fires on a
            # real, deterministic difference (see its own docstring). A
            # removed element can be a tiny fraction of total page pixels
            # (easily under threshold) while still being a completely real
            # defect a human needs to see — gating THAT behind the same
            # noise-reduction AND-gate designed for the CNN's fuzzy guesses
            # silently auto-passes exactly the class of small-but-real
            # structural defect DOM-diff exists to catch.
            dom_confirmed = bool(ai_assessment and ai_assessment.get("dom_confirmed"))
            passed = not (meaningful and (pixel_fail or dom_confirmed))
            decision_source = "hybrid"
        else:
            passed = pixel_pass
            decision_source = "pixel-fallback-ai-error" if ai_error else "pixel-fallback-no-model"

    return passed, {
        "comparison_mode": mode,
        "decision_source": decision_source,
        "pixel_would_pass": pixel_pass,
        "meaningful_change": meaningful,
        "ai_error": ai_error,
    }
