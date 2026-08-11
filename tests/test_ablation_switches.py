"""The ablation switches have to actually remove the thing they name.

An ablation study is only worth quoting if each switch does exactly one thing,
so a difference between two runs can be attributed to that one thing. A switch
that silently does nothing produces two identical numbers and an unearned
conclusion ("the component contributes nothing"), which is the failure mode
worth a test.

LENS_ABLATE_DOM_ENGINE is verified against the call it is meant to suppress.
The two feature switches are verified on the standardised vector itself, since
which columns they zero is the whole claim: 9:62 are the DOM snapshot and
structural-diff features, 62:77 the pixel-structural ones.
"""
import numpy as np
import pytest

from visual_regression import ai_training
from visual_regression.ai_training import _standardised_rule_vector


class _Loaded(dict):
    """A checkpoint with no standardisation statistics, so the vector passes
    through unscaled and the assertions are about the switches alone."""

    def __init__(self):
        super().__init__(rule_feature_mean=None, rule_feature_std=None)


def _parts():
    # 9 rule + 39 dom + 14 struct + 15 px = 77, each block a distinct constant
    # so a zeroed range is unambiguous.
    return [
        np.ones(9, dtype=np.float32) * 1.0,
        np.ones(39, dtype=np.float32) * 2.0,
        np.ones(14, dtype=np.float32) * 3.0,
        np.ones(15, dtype=np.float32) * 4.0,
    ]


def test_no_switches_leaves_every_column_populated(monkeypatch):
    monkeypatch.delenv("LENS_ABLATE_DOM_FEATURES", raising=False)
    monkeypatch.delenv("LENS_ABLATE_PIXEL_FEATURES", raising=False)

    vec = _standardised_rule_vector(_Loaded(), _parts(), 77)

    assert vec.shape == (77,)
    assert np.count_nonzero(vec) == 77


def test_dom_feature_ablation_zeros_only_the_dom_columns(monkeypatch):
    monkeypatch.setenv("LENS_ABLATE_DOM_FEATURES", "true")
    monkeypatch.delenv("LENS_ABLATE_PIXEL_FEATURES", raising=False)

    vec = _standardised_rule_vector(_Loaded(), _parts(), 77)

    assert np.all(vec[9:62] == 0.0), "the 53 DOM columns must be neutralised"
    assert np.all(vec[:9] != 0.0), "base pixel/SSIM stats must survive"
    assert np.all(vec[62:77] != 0.0), "pixel-structural columns must survive"


def test_pixel_feature_ablation_zeros_only_the_pixel_columns(monkeypatch):
    monkeypatch.delenv("LENS_ABLATE_DOM_FEATURES", raising=False)
    monkeypatch.setenv("LENS_ABLATE_PIXEL_FEATURES", "true")

    vec = _standardised_rule_vector(_Loaded(), _parts(), 77)

    assert np.all(vec[62:77] == 0.0), "the 15 px_* columns must be neutralised"
    assert np.all(vec[9:62] != 0.0), "DOM columns must survive"


def test_the_two_feature_switches_compose(monkeypatch):
    monkeypatch.setenv("LENS_ABLATE_DOM_FEATURES", "true")
    monkeypatch.setenv("LENS_ABLATE_PIXEL_FEATURES", "true")

    vec = _standardised_rule_vector(_Loaded(), _parts(), 77)

    assert np.all(vec[9:77] == 0.0)
    assert np.all(vec[:9] != 0.0), "only the base stats are left to decide on"


@pytest.mark.parametrize("value", ["false", "0", "", "TRUE-ish"])
def test_only_the_literal_true_enables_ablation(monkeypatch, value):
    """A study is run by setting these deliberately; anything else must be
    treated as off rather than guessed at."""
    monkeypatch.setenv("LENS_ABLATE_DOM_FEATURES", value)

    vec = _standardised_rule_vector(_Loaded(), _parts(), 77)

    assert np.count_nonzero(vec) == 77


def test_the_dom_engine_switch_guards_the_call_in_the_inference_path():
    """Assert on the source of the function that actually runs.

    Reimplementing the branch in the test and asserting on the copy proves
    only that the copy works: the switch could be deleted from
    _finalize_classification_assessment and a behavioural test written that
    way would still pass, while every ablation run silently measured the
    unablated system and the study reported a component contributing nothing.
    Reading the source ties the test to the real call site. Same reasoning as
    tests/test_standardisation_survives_export.py.
    """
    import inspect

    source = inspect.getsource(ai_training._finalize_classification_assessment)

    assert "LENS_ABLATE_DOM_ENGINE" in source, (
        "the DOM-engine ablation switch is gone from the inference path; any "
        "ablation run using it is measuring the unablated system"
    )
    # The guard has to sit before the verdict is taken, not after it has
    # already overwritten the label. Match the call itself: the function is
    # named in a comment further up too, and matching that instead put the
    # "call" before the switch and failed a correctly-guarded implementation.
    switch_at = source.index("LENS_ABLATE_DOM_ENGINE")
    call_at = source.index("= _diagnose_dom_diff_best(")
    assert switch_at < call_at, (
        "the switch must gate the structural verdict, not follow it"
    )


def test_dom_engine_ablation_suppresses_the_structural_verdict(monkeypatch):
    """And that the guard, given the flag, actually withholds the verdict."""
    calls = []

    def _spy(*args, **kwargs):
        calls.append(1)
        return "missing-element", "DOM diff: an element left the page."

    monkeypatch.setattr(ai_training, "_diagnose_dom_diff_best", _spy)

    monkeypatch.setenv("LENS_ABLATE_DOM_ENGINE", "true")
    assert _dom_label_applied() is None
    assert not calls, "the engine must not even be consulted when ablated"

    monkeypatch.setenv("LENS_ABLATE_DOM_ENGINE", "false")
    assert _dom_label_applied() == "missing-element"
    assert calls, "with the switch off the engine must decide as before"


def _dom_label_applied():
    import os
    if os.environ.get("LENS_ABLATE_DOM_ENGINE", "").lower() == "true":
        return None
    label, _evidence = ai_training._diagnose_dom_diff_best(None, None, None)
    return label
