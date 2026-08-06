"""DOM-dropout: making the screenshot-only case part of the training distribution.

Every real training pair carries a DOM sidecar, and the DOM block is predictive
enough (the rule engine reaches 94% from it alone) that a model trained with it
never needs its image streams. At screenshot-only inference the block arrives
as zeros — an input the model has never seen — and predictions collapse toward
one class. Dropout zeroes that block on a fraction of training samples so the
pixels have to carry those samples.

These pin the helper's contract; whether it improves the live no-DOM number is
measured by the evaluation, not asserted here.
"""
import numpy as np

from visual_regression.ai_features import FULL_FEATURE_NAMES, RULE_FEATURE_NAMES
from visual_regression.ai_training import _apply_dom_dropout

PIXEL = len(RULE_FEATURE_NAMES)


def batch(n=8):
    return np.arange(n * len(FULL_FEATURE_NAMES), dtype=np.float32).reshape(n, -1) + 1.0


def test_p_zero_is_a_no_op_and_does_not_copy():
    rules = batch()
    out = _apply_dom_dropout(rules, 0.0, np.random.default_rng(0))
    assert out is rules


def test_p_one_zeroes_the_dom_block_on_every_sample():
    rules = batch()
    out = _apply_dom_dropout(rules, 1.0, np.random.default_rng(0))

    assert np.all(out[:, PIXEL:] == 0.0), "the DOM+struct block must be zeroed"
    assert np.all(out[:, :PIXEL] == rules[:, :PIXEL]), (
        "the pixel features are always available at inference and must never be dropped"
    )


def test_the_callers_array_is_not_mutated():
    """The collate output is reused as the model input elsewhere in the loop;
    dropping in place would silently alter it for any later consumer."""
    rules = batch()
    before = rules.copy()

    _apply_dom_dropout(rules, 1.0, np.random.default_rng(0))

    assert np.array_equal(rules, before)


def test_dropout_is_per_sample_not_per_batch():
    """At 0.5 a large batch must contain both dropped and kept samples —
    per-batch dropout would starve one modality for whole batches at a time."""
    rules = batch(n=400)
    out = _apply_dom_dropout(rules, 0.5, np.random.default_rng(7))

    dropped = np.all(out[:, PIXEL:] == 0.0, axis=1)
    assert 100 < dropped.sum() < 300, f"{dropped.sum()}/400 dropped — not per-sample"
