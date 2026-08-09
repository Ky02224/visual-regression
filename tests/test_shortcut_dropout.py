"""Both shortcuts the model can take, and how training removes them.

A model that can reach low loss through one input never learns the others. Two
were measured on this system:

  DOM: the block is so predictive that the image pathway is never forced to
  classify. Zeroing it at inference then puts the model out of distribution —
  91.2% with it, 60.0% without; trained with dropout, 90.2% and 79.5%.

  images: they encode how much of the page changed, and that alone reproduces
  83.2% of the model's own predictions, whose classes sort by it (0.00, 0.29,
  0.30, 1.16, 2.37, 3.84, 6.51). The same number predicts the true label 66.8%
  of the time against the model's 37.0%. Four classes overlap in magnitude —
  layout-issue, text-issue, broken-image, font-change — and they are exactly the
  four that collapse in every run.

The pixel features must survive both, since they are what remains when there is
no DOM and what separates those four.
"""
import numpy as np
import pytest

torch = pytest.importorskip("torch")

from visual_regression.ai_features import (  # noqa: E402
    DOM_FEATURE_NAMES,
    PIXEL_STRUCT_FEATURE_NAMES,
    RULE_FEATURE_NAMES,
    STRUCT_FEATURE_NAMES,
)
from visual_regression.ai_training import (  # noqa: E402
    _apply_dom_dropout,
    _apply_image_dropout,
)

nR, nD, nS, nP = (len(RULE_FEATURE_NAMES), len(DOM_FEATURE_NAMES),
                  len(STRUCT_FEATURE_NAMES), len(PIXEL_STRUCT_FEATURE_NAMES))
WIDTH = nR + nD + nS + nP


class TestDomDropout:
    def test_it_zeroes_the_dom_and_structural_blocks(self):
        rows = np.ones((200, WIDTH), dtype=np.float32)

        out = _apply_dom_dropout(rows, 1.0, np.random.default_rng(0))

        assert (out[:, nR:nR + nD + nS] == 0).all()

    def test_the_pixel_block_survives(self):
        """It is measured from the screenshots, so it is present with or without
        a DOM sidecar — and it is what separates the four classes the model
        cannot otherwise tell apart. Zeroing it alongside the DOM taught the
        model that 'no DOM' means 'no evidence', the opposite of the truth."""
        rows = np.ones((200, WIDTH), dtype=np.float32)

        out = _apply_dom_dropout(rows, 1.0, np.random.default_rng(0))

        assert (out[:, nR + nD + nS:] == 1).all(), "the pixel features were dropped too"

    def test_the_rule_block_survives(self):
        rows = np.ones((200, WIDTH), dtype=np.float32)

        out = _apply_dom_dropout(rows, 1.0, np.random.default_rng(0))

        assert (out[:, :nR] == 1).all()

    def test_zero_probability_changes_nothing(self):
        rows = np.ones((50, WIDTH), dtype=np.float32)

        assert _apply_dom_dropout(rows, 0.0, np.random.default_rng(0)) is rows

    def test_it_applies_to_roughly_the_requested_fraction(self):
        rows = np.ones((4000, WIDTH), dtype=np.float32)

        out = _apply_dom_dropout(rows, 0.5, np.random.default_rng(0))
        dropped = (out[:, nR] == 0).mean()

        assert 0.45 < dropped < 0.55

    def test_the_input_is_not_modified_in_place(self):
        """The caller reuses the batch; zeroing it would silently drop the DOM
        for every later epoch as well."""
        rows = np.ones((100, WIDTH), dtype=np.float32)

        _apply_dom_dropout(rows, 1.0, np.random.default_rng(0))

        assert (rows == 1).all()


class TestImageDropout:
    def build(self, n=200, image_dim=64):
        return torch.ones(n, image_dim + WIDTH), WIDTH

    def test_it_zeroes_the_image_columns(self):
        combined, rule_dim = self.build()

        out = _apply_image_dropout(combined, rule_dim, 1.0, np.random.default_rng(0), torch)

        assert (out[:, :-rule_dim] == 0).all()

    def test_the_feature_columns_are_untouched(self):
        """Removing the shortcut is the point; removing the evidence is not."""
        combined, rule_dim = self.build()

        out = _apply_image_dropout(combined, rule_dim, 1.0, np.random.default_rng(0), torch)

        assert (out[:, -rule_dim:] == 1).all()

    def test_zero_probability_returns_the_same_tensor(self):
        combined, rule_dim = self.build()

        assert _apply_image_dropout(combined, rule_dim, 0.0, np.random.default_rng(0), torch) is combined

    def test_it_applies_per_sample_not_per_batch(self):
        combined, rule_dim = self.build(n=4000)

        out = _apply_image_dropout(combined, rule_dim, 0.5, np.random.default_rng(0), torch)
        dropped = (out[:, 0] == 0).float().mean().item()

        assert 0.45 < dropped < 0.55

    def test_the_shape_is_preserved(self):
        combined, rule_dim = self.build()

        out = _apply_image_dropout(combined, rule_dim, 0.5, np.random.default_rng(0), torch)

        assert out.shape == combined.shape

    def test_gradients_still_flow_to_the_kept_samples(self):
        """Dropping half the batch's images must not detach the other half."""
        combined = torch.ones(100, 64 + WIDTH, requires_grad=True)

        out = _apply_image_dropout(combined, WIDTH, 0.5, np.random.default_rng(0), torch)
        out.sum().backward()

        assert combined.grad is not None and combined.grad.abs().sum() > 0
