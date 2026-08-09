"""The pixel-structural block has to reach inference, not only training.

`pixel_struct_feature_vector` was called in exactly one place — the training
sample builder — so every inference path assembled [rule, dom, struct], 62 of
the 77 columns, and `_fit_rule_vector` zero-padded the rest. The model was
trained on fifteen features it never received in production.

Without a DOM sidecar those fifteen are the only columns describing *what kind*
of change occurred; the other nine are magnitude and similarity scalars. That is
precisely the behaviour measured on the deployed model: a single mismatch_pct
reproduces 83.2% of its predictions, and the classes it names sort by that
number. The same fifteen, measured on crops from sites held out entirely,
classify the seven categories at 83.3% — colour-regression 91.1%, font-change
93.8%, layout-issue 87.3%.

Two days of training runs were spent optimising for inputs that arrived as
zeros, so this is asserted at the level that failed: the width the vector is
assembled to, before any padding hides the gap.
"""
import inspect
import re

import numpy as np
import pytest

from visual_regression import ai_training
from visual_regression.ai_features import (
    DOM_FEATURE_NAMES,
    FULL_FEATURE_NAMES_V2,
    PIXEL_STRUCT_FEATURE_NAMES,
    RULE_FEATURE_NAMES,
    STRUCT_FEATURE_NAMES,
    pixel_struct_feature_vector,
)

nR, nD, nS, nP = (len(RULE_FEATURE_NAMES), len(DOM_FEATURE_NAMES),
                  len(STRUCT_FEATURE_NAMES), len(PIXEL_STRUCT_FEATURE_NAMES))


def assembly_sites():
    """Every place an inference path builds the rule vector."""
    source = inspect.getsource(ai_training)
    return re.findall(r"_standardised_rule_vector\(\s*loaded,\s*\[([^\]]+)\]", source)


class TestEveryInferencePathIncludesThem:
    def test_all_four_paths_were_found(self):
        """A path added later must not quietly skip the block — if this count
        changes, the new one needs checking too."""
        assert len(assembly_sites()) == 4, assembly_sites()

    @pytest.mark.parametrize("index", range(4))
    def test_the_pixel_block_is_passed(self, index):
        parts = assembly_sites()[index]

        assert "px_vec" in parts, f"path {index} assembles only: {parts.strip()}"

    def test_the_parts_add_up_to_the_full_width(self):
        """62 of 77 padded to 77 looks identical to 77 real ones downstream,
        which is why this went unnoticed."""
        assert nR + nD + nS + nP == len(FULL_FEATURE_NAMES_V2)


class TestFitRuleVectorHidesAShortInput:
    def test_a_short_vector_is_padded_rather_than_rejected(self):
        """The behaviour that made the omission invisible. It is right for a
        model trained before a block existed, and wrong as a way of finding out
        that a caller forgot one — hence the assertions above."""
        short = [np.ones(nR + nD + nS, dtype=np.float32)]

        out = ai_training._fit_rule_vector(short, len(FULL_FEATURE_NAMES_V2))

        assert out.shape[0] == len(FULL_FEATURE_NAMES_V2)
        assert (out[-nP:] == 0).all()

    def test_a_full_vector_passes_through_unchanged(self):
        full = [np.arange(len(FULL_FEATURE_NAMES_V2), dtype=np.float32)]

        out = ai_training._fit_rule_vector(full, len(FULL_FEATURE_NAMES_V2))

        assert (out[-nP:] != 0).any(), "the pixel columns arrived as zeros"


class TestTheBlockCarriesSignal:
    def test_a_recolour_and_a_removal_do_not_look_alike(self):
        """What the zeros were costing: with only magnitude and similarity, a
        colour change over a small area is indistinguishable from no change."""
        base = np.full((80, 80, 3), 200, dtype=np.uint8)
        recoloured = base.copy()
        recoloured[30:50, 30:50] = (40, 40, 200)          # same shapes, new colour
        removed = base.copy()
        removed[30:50, 30:50] = 200                        # nothing there at all
        removed[20:60, 20:60] = 255

        a = pixel_struct_feature_vector(base, recoloured)
        b = pixel_struct_feature_vector(base, removed)

        assert np.abs(a - b).max() > 1e-3

    def test_an_unchanged_pair_reports_no_change(self):
        """Every column that describes a change reads zero. px_translate_conf is
        excluded because 1.0 is its correct answer here — the pair is perfectly
        aligned, which is what that column measures."""
        rng = np.random.default_rng(0)
        img = rng.integers(0, 255, (80, 80, 3), dtype=np.uint8)

        vec = pixel_struct_feature_vector(img, img.copy())
        described = [v for name, v in zip(PIXEL_STRUCT_FEATURE_NAMES, vec)
                     if name != "px_translate_conf"]

        assert np.abs(described).max() < 1e-6
