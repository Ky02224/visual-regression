"""Tests for the synthetic training-data generator.

328 statements at 10% coverage, and this module *is* the AI's training set: every
label the model learns comes from `_apply_defect_variant` doing what its mode
name says. A mode that silently produces no visible change teaches the model
that that defect class looks identical to a clean page — the same failure the
demo portal's missing `.z-index-issue` CSS caused on the benchmark side.

So the central assertion here is simply: a defect variant must differ from its
source, and a benign variant must stay close to it. That is the property the
whole training pipeline rests on.
"""

from __future__ import annotations

import numpy as np
import pytest

from visual_regression.dataset_generator import (
    BENIGN_LABEL_NAME,
    DEFECT_LABELS,
    DEFECT_MODES,
    _apply_benign_variant,
    _apply_defect_variant,
    _draw_base_ui,
    _load_base_images,
    _resize_to_max,
    _sample_bg_color,
)
from visual_regression.config import WorkspacePaths


def _difference_pct(a: np.ndarray, b: np.ndarray) -> float:
    """Share of pixels differing by more than a small tolerance."""
    if a.shape != b.shape:
        return 100.0
    delta = np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2)
    return float((delta > 12).mean() * 100.0)


@pytest.fixture
def base_ui():
    return _draw_base_ui(seed=7, width=480, height=320)


# ---------------------------------------------------------------------------
# The synthetic canvas
# ---------------------------------------------------------------------------

class TestDrawBaseUi:
    def test_produces_a_three_channel_image_of_the_requested_size(self):
        image = _draw_base_ui(seed=1, width=300, height=200)
        assert image.shape == (200, 300, 3)
        assert image.dtype == np.uint8

    def test_is_deterministic_for_a_seed(self):
        assert np.array_equal(_draw_base_ui(seed=3), _draw_base_ui(seed=3))

    def test_different_seeds_draw_different_layouts(self):
        assert not np.array_equal(_draw_base_ui(seed=1), _draw_base_ui(seed=2))

    def test_is_not_a_blank_canvas(self):
        """A flat image would give the model nothing to key on."""
        image = _draw_base_ui(seed=5, width=320, height=240)
        assert image.std() > 5


# ---------------------------------------------------------------------------
# Defect variants — the property the training labels depend on
# ---------------------------------------------------------------------------

class TestDefectVariants:
    @pytest.mark.parametrize("mode", DEFECT_MODES)
    def test_every_mode_changes_the_image(self, base_ui, mode):
        """If a mode leaves the page untouched, every sample labelled with it
        teaches the model that this defect looks exactly like a clean page."""
        variant, _ = _apply_defect_variant(base_ui, seed=11, mode=mode)
        assert _difference_pct(base_ui, variant) > 0.05, f"{mode} produced no visible change"

    @pytest.mark.parametrize("mode", DEFECT_MODES)
    def test_every_mode_returns_the_matching_label(self, base_ui, mode):
        """The returned label becomes the training target. A mode that reports
        someone else's label mislabels every sample it generates."""
        _, label = _apply_defect_variant(base_ui, seed=11, mode=mode)
        assert label == mode.replace("_", "-")
        assert label in DEFECT_LABELS

    @pytest.mark.parametrize("mode", DEFECT_MODES)
    def test_every_mode_preserves_shape_and_dtype(self, base_ui, mode):
        variant, _ = _apply_defect_variant(base_ui, seed=11, mode=mode)
        assert variant.shape == base_ui.shape
        assert variant.dtype == np.uint8

    @pytest.mark.parametrize("mode", DEFECT_MODES)
    def test_every_mode_is_deterministic_for_a_seed(self, base_ui, mode):
        """Reproducibility is what makes a reported accuracy re-checkable."""
        first, first_label = _apply_defect_variant(base_ui, seed=23, mode=mode)
        second, second_label = _apply_defect_variant(base_ui, seed=23, mode=mode)
        assert np.array_equal(first, second)
        assert first_label == second_label

    def test_does_not_mutate_the_source_image(self, base_ui):
        """In-place edits would corrupt the baseline half of the training pair."""
        original = base_ui.copy()
        for mode in DEFECT_MODES:
            _apply_defect_variant(base_ui, seed=31, mode=mode)
        assert np.array_equal(base_ui, original)

    def test_mode_defaults_to_a_random_choice(self, base_ui):
        variant, label = _apply_defect_variant(base_ui, seed=41)
        assert variant.shape == base_ui.shape
        assert label in DEFECT_LABELS
        assert _difference_pct(base_ui, variant) > 0.0

    def test_different_seeds_place_the_defect_differently(self, base_ui):
        a, _ = _apply_defect_variant(base_ui, seed=1, mode="missing_element")
        b, _ = _apply_defect_variant(base_ui, seed=999, mode="missing_element")
        assert not np.array_equal(a, b)

    def test_handles_a_small_image_without_crashing(self):
        """Public-dataset thumbnails can be far smaller than the synthetic canvas."""
        tiny = np.full((64, 64, 3), 220, dtype=np.uint8)
        for mode in DEFECT_MODES:
            variant, label = _apply_defect_variant(tiny, seed=13, mode=mode)
            assert variant.shape == tiny.shape
            assert label in DEFECT_LABELS


# ---------------------------------------------------------------------------
# Benign variants — the negative class
# ---------------------------------------------------------------------------

class TestBenignVariants:
    def test_perturbation_stays_within_the_documented_range(self, base_ui):
        """Benign variants model rendering noise — brightness +/-12, contrast
        0.88-1.12, sigma 2.5 noise, and occasional blur/shift/JPEG. Bound the
        aggregate so a future edit cannot quietly turn the negative class into
        something as different from the source as a real defect is.

        Note this is a *photometric* bound, not a structural one. Measured on
        this canvas, benign SSIM spans 0.77-0.97 and defect SSIM 0.79-1.00 —
        they overlap almost entirely, so SSIM alone cannot separate the two
        classes here. That is a property of the synthetic data, not of this
        test, and it is why the model leans on the CNN embedding rather than
        the rule features for this distinction.
        """
        for seed in range(20):
            variant = _apply_benign_variant(base_ui, seed=seed)
            mad = np.abs(base_ui.astype(np.int16) - variant.astype(np.int16)).mean()
            assert mad < 40.0, f"seed {seed} perturbed the image far beyond the documented range"

    def test_preserves_shape_and_dtype(self, base_ui):
        for seed in range(8):
            variant = _apply_benign_variant(base_ui, seed=seed)
            assert variant.shape == base_ui.shape
            assert variant.dtype == np.uint8

    def test_is_deterministic_for_a_seed(self, base_ui):
        assert np.array_equal(
            _apply_benign_variant(base_ui, seed=17), _apply_benign_variant(base_ui, seed=17)
        )

    def test_does_not_mutate_the_source_image(self, base_ui):
        original = base_ui.copy()
        for seed in range(6):
            _apply_benign_variant(base_ui, seed=seed)
        assert np.array_equal(base_ui, original)

    def test_actually_perturbs_the_image(self, base_ui):
        """A no-op benign variant would make the negative class trivially
        separable and inflate the reported accuracy."""
        variant = _apply_benign_variant(base_ui, seed=2)
        assert not np.array_equal(base_ui, variant)


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

class TestTaxonomy:
    def test_every_mode_has_a_matching_label(self):
        """DEFECT_MODES uses underscores and DEFECT_LABELS hyphens; a mode with
        no label cannot be turned into a training target."""
        assert len(DEFECT_MODES) == len(DEFECT_LABELS)
        assert {m.replace("_", "-") for m in DEFECT_MODES} == set(DEFECT_LABELS)

    def test_labels_are_unique(self):
        assert len(set(DEFECT_LABELS)) == len(DEFECT_LABELS)

    def test_benign_label_is_not_one_of_the_defects(self):
        assert BENIGN_LABEL_NAME not in DEFECT_LABELS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestResizeToMax:
    def test_shrinks_an_oversized_image(self):
        big = np.zeros((1000, 2000, 3), dtype=np.uint8)
        out = _resize_to_max(big, 500)
        assert max(out.shape[:2]) <= 500

    def test_preserves_aspect_ratio(self):
        big = np.zeros((500, 1000, 3), dtype=np.uint8)
        out = _resize_to_max(big, 200)
        assert out.shape[1] / out.shape[0] == pytest.approx(2.0, abs=0.05)

    def test_leaves_a_small_image_alone(self):
        small = np.zeros((50, 80, 3), dtype=np.uint8)
        assert _resize_to_max(small, 500).shape == small.shape


class TestSampleBgColour:
    def test_returns_the_local_colour(self):
        image = np.full((40, 40, 3), 130, dtype=np.uint8)
        assert _sample_bg_color(image, 20, 20) == (130, 130, 130)

    def test_clamps_at_the_edges_instead_of_indexing_out_of_bounds(self):
        image = np.full((40, 40, 3), 90, dtype=np.uint8)
        assert _sample_bg_color(image, 0, 0) == (90, 90, 90)
        assert _sample_bg_color(image, 39, 39) == (90, 90, 90)


class TestLoadBaseImages:
    def test_falls_back_to_drawn_canvases_when_no_baselines_exist(self, tmp_path):
        """Training must still be possible in a fresh workspace."""
        paths = WorkspacePaths(tmp_path / ".visual-regression")
        paths.ensure()
        images = _load_base_images(paths)
        assert len(images) > 0
        assert all(img.ndim == 3 for img in images)
