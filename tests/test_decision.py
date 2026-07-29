from visual_regression.decision import decide_pass_fail, normalize_comparison_mode, pixel_would_pass


def test_pixel_mode_uses_threshold():
    passed, meta = decide_pass_fail(
        comparison_mode="pixel",
        mismatch_pct=0.2,
        threshold_pct=0.5,
        ai_assessment={"label": "layout-shift", "meaningful_change": True},
        ai_model_available=True,
    )
    assert passed is True
    assert meta["decision_source"] == "pixel"


def test_ai_mode_ignores_pixel_fail_when_benign():
    passed, meta = decide_pass_fail(
        comparison_mode="ai",
        mismatch_pct=5.0,
        threshold_pct=0.5,
        ai_assessment={"label": "", "meaningful_change": False},
        ai_model_available=True,
    )
    assert passed is True
    assert meta["decision_source"] == "ai"
    assert meta["pixel_would_pass"] is False


def test_ai_mode_fails_on_meaningful_change():
    passed, meta = decide_pass_fail(
        comparison_mode="ai",
        mismatch_pct=0.1,
        threshold_pct=0.5,
        ai_assessment={"label": "missing-element", "meaningful_change": True},
        ai_model_available=True,
    )
    assert passed is False
    assert meta["meaningful_change"] is True


def test_hybrid_requires_both_signals():
    passed, _ = decide_pass_fail(
        comparison_mode="hybrid",
        mismatch_pct=5.0,
        threshold_pct=0.5,
        ai_assessment={"label": "", "meaningful_change": False},
        ai_model_available=True,
    )
    assert passed is True

    passed, _ = decide_pass_fail(
        comparison_mode="hybrid",
        mismatch_pct=5.0,
        threshold_pct=0.5,
        ai_assessment={"label": "layout-shift", "meaningful_change": True},
        ai_model_available=True,
    )
    assert passed is False


def test_hybrid_dom_confirmed_defect_fails_despite_small_pixel_delta():
    # A real, deterministically-confirmed DOM-diff verdict (an element
    # genuinely removed, per diagnose_from_dom_diff comparing actual
    # before/after structure) must fail the build even when the removed
    # element is a small fraction of total page pixels — this is exactly
    # the class of defect DOM-diff exists to catch that a pure pixel
    # threshold would miss. Regression test for a real bug found via a
    # true end-to-end run (real capture -> real compare -> real decision):
    # the old `pixel_fail and meaningful` gate silently auto-passed this.
    passed, meta = decide_pass_fail(
        comparison_mode="hybrid",
        mismatch_pct=0.18,  # well under threshold on its own
        threshold_pct=0.5,
        ai_assessment={
            "label": "missing-element",
            "meaningful_change": True,
            "dom_confirmed": True,
        },
        ai_model_available=True,
    )
    assert passed is False
    assert meta["pixel_would_pass"] is True


def test_hybrid_still_requires_pixel_corroboration_for_non_dom_verdicts():
    # The original noise-reduction behavior (test_hybrid_requires_both_signals)
    # must still hold for a plain CNN-score verdict with no DOM-diff backing
    # it — only dom_confirmed verdicts bypass the pixel corroboration gate.
    passed, _ = decide_pass_fail(
        comparison_mode="hybrid",
        mismatch_pct=0.18,
        threshold_pct=0.5,
        ai_assessment={"label": "layout-shift", "meaningful_change": True, "dom_confirmed": False},
        ai_model_available=True,
    )
    assert passed is True


def test_ai_mode_falls_back_without_model():
    passed, meta = decide_pass_fail(
        comparison_mode="ai",
        mismatch_pct=5.0,
        threshold_pct=0.5,
        ai_assessment={},
        ai_model_available=False,
    )
    assert passed is False
    assert meta["decision_source"] == "pixel-fallback-no-model"


def test_normalize_comparison_mode():
    assert normalize_comparison_mode("AI") == "ai"
    assert pixel_would_pass(0.4, 0.5) is True
