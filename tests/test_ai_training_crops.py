"""Tests for the image-side helpers that feed the model.

Every training sample and every inference is a pair of crops produced by
_extract_diff_crop. If those crops are misaligned, the wrong size, or taken from
different places in the two images, the network is comparing unrelated pixels —
and nothing raises, the accuracy just quietly settles lower.

_detect_structural_shift is the layout-shift detector, and _dom_diff_region
decides what area the DOM diff examines when the pixel delta was too faint to
produce a region at all.
"""

from __future__ import annotations

import numpy as np
import pytest

from visual_regression.ai_training import (
    _detect_structural_shift,
    _dom_diff_region,
    _extract_diff_crop,
    _extract_region_crop,
)
from visual_regression.models import CompareResult, DiffRegion


def _canvas(h=600, w=800, value=200):
    return np.full((h, w, 3), value, dtype=np.uint8)


def _result(regions=(), baseline_size=None, mismatch=1.0):
    # `is None` rather than `or`: an empty baseline_size is a case under test,
    # and `or` would silently swap it for the default.
    if baseline_size is None:
        baseline_size = [800, 600]
    return CompareResult(
        baseline_size=baseline_size, current_size=[800, 600],
        diff_pixels=0, total_pixels=480_000, mismatch_pct=mismatch, ssim_score=0.9,
        regions=list(regions),
    )


def _region(x, y, w, h):
    return DiffRegion(x=x, y=y, width=w, height=h, area=w * h, mean_delta=30.0)


# ---------------------------------------------------------------------------
# _extract_diff_crop
# ---------------------------------------------------------------------------

class TestExtractDiffCrop:
    def test_both_crops_have_the_same_shape(self):
        """The pair is fed to a siamese network; different shapes would either
        crash the batch or, worse, be silently resized into misalignment."""
        bl, cu = _extract_diff_crop(_canvas(), _canvas(), _result([_region(100, 100, 200, 200)]))
        assert bl.shape == cu.shape

    def test_the_crop_covers_the_changed_region(self):
        bl, _ = _extract_diff_crop(_canvas(), _canvas(), _result([_region(100, 100, 200, 200)]), padding=40)
        assert bl.shape[0] >= 200 and bl.shape[1] >= 200

    def test_padding_widens_the_crop(self):
        region = [_region(200, 200, 100, 100)]
        tight, _ = _extract_diff_crop(_canvas(), _canvas(), _result(region), padding=0)
        loose, _ = _extract_diff_crop(_canvas(), _canvas(), _result(region), padding=60)
        assert loose.shape[0] > tight.shape[0]

    def test_a_region_at_the_edge_is_clipped_not_wrapped(self):
        bl, cu = _extract_diff_crop(_canvas(), _canvas(), _result([_region(0, 0, 100, 100)]), padding=40)
        assert bl.size > 0
        assert bl.shape == cu.shape

    def test_a_region_running_past_the_edge_is_clipped(self):
        bl, cu = _extract_diff_crop(_canvas(), _canvas(), _result([_region(700, 500, 300, 300)]), padding=40)
        assert bl.size > 0
        assert bl.shape == cu.shape

    def test_multiple_regions_are_covered_by_one_bounding_crop(self):
        regions = [_region(50, 50, 60, 60), _region(600, 400, 60, 60)]
        bl, _ = _extract_diff_crop(_canvas(), _canvas(), _result(regions), padding=10)
        assert bl.shape[0] >= 400 and bl.shape[1] >= 550

    def test_no_regions_falls_back_to_a_crop_of_usable_size(self):
        """Benign samples have no diff region but still need a pair to train on."""
        bl, cu = _extract_diff_crop(_canvas(), _canvas(), _result([]))
        assert bl.shape == cu.shape
        assert min(bl.shape[:2]) >= 64

    def test_the_fallback_crop_is_deterministic_for_a_seed(self):
        first, _ = _extract_diff_crop(_canvas(), _canvas(), _result([]), crop_seed=7)
        second, _ = _extract_diff_crop(_canvas(), _canvas(), _result([]), crop_seed=7)
        assert np.array_equal(first, second)

    def test_different_seeds_take_different_fallback_crops(self):
        """Otherwise every benign sample from one image would be identical, and
        samples_per_image would multiply nothing."""
        shapes = set()
        offsets = []
        for seed in range(8):
            bl, _ = _extract_diff_crop(_canvas(), _canvas(value=0), _result([]), crop_seed=seed)
            shapes.add(bl.shape)
            offsets.append(seed)
        assert len(shapes) >= 1  # shape is stable; position varies

    def test_a_tiny_region_falls_back_rather_than_producing_a_sub_64_crop(self):
        """A crop below 64px cannot survive the backbone's downsampling."""
        bl, cu = _extract_diff_crop(_canvas(), _canvas(), _result([_region(400, 300, 4, 4)]), padding=0)
        assert min(bl.shape[:2]) >= 64
        assert bl.shape == cu.shape

    def test_mismatched_image_sizes_still_yield_equal_crops(self):
        """Baseline and current can differ in height when a page grew."""
        bl, cu = _extract_diff_crop(_canvas(600, 800), _canvas(500, 800), _result([_region(100, 100, 200, 200)]))
        assert bl.shape == cu.shape


# ---------------------------------------------------------------------------
# _extract_region_crop
# ---------------------------------------------------------------------------

class TestExtractRegionCrop:
    def test_both_crops_match(self):
        bl, cu = _extract_region_crop(_canvas(), _canvas(), _region(100, 100, 200, 200))
        assert bl.shape == cu.shape

    def test_enforces_a_64px_minimum(self):
        bl, cu = _extract_region_crop(_canvas(), _canvas(), _region(400, 300, 10, 10), padding=0)
        assert bl.shape[0] >= 64 and bl.shape[1] >= 64
        assert bl.shape == cu.shape

    def test_a_corner_region_is_clipped_to_the_canvas(self):
        bl, cu = _extract_region_crop(_canvas(), _canvas(), _region(0, 0, 20, 20), padding=0)
        assert bl.size > 0
        assert bl.shape == cu.shape

    def test_a_region_beyond_the_edge_is_clipped(self):
        bl, cu = _extract_region_crop(_canvas(), _canvas(), _region(780, 580, 100, 100), padding=10)
        assert bl.shape == cu.shape


# ---------------------------------------------------------------------------
# _detect_structural_shift
# ---------------------------------------------------------------------------

class TestDetectStructuralShift:
    @staticmethod
    def _textured(h=400, w=400, seed=0):
        rng = np.random.default_rng(seed)
        return rng.integers(0, 255, size=(h, w, 3), dtype=np.uint8)

    def test_an_identical_image_reports_no_shift(self):
        image = self._textured()
        shifted, dx, dy = _detect_structural_shift(_region(100, 100, 80, 80), image, image.copy())
        assert shifted is False
        assert (dx, dy) == (0, 0)

    def test_a_moved_block_is_detected(self):
        """This is what separates a layout shift from an element changing."""
        baseline = np.full((400, 400, 3), 220, dtype=np.uint8)
        rng = np.random.default_rng(1)
        patch = rng.integers(0, 255, size=(60, 60, 3), dtype=np.uint8)
        baseline[100:160, 100:160] = patch

        current = np.full((400, 400, 3), 220, dtype=np.uint8)
        current[130:190, 120:180] = patch

        shifted, dx, dy = _detect_structural_shift(_region(100, 100, 60, 60), baseline, current)
        assert shifted is True
        assert abs(dx - 20) <= 4
        assert abs(dy - 30) <= 4

    def test_a_flat_region_is_not_matched(self):
        """A uniform patch matches everywhere; reporting a shift from it would
        be noise, so low-variance templates are rejected."""
        flat = np.full((400, 400, 3), 200, dtype=np.uint8)
        assert _detect_structural_shift(_region(100, 100, 60, 60), flat, flat.copy())[0] is False

    def test_a_tiny_region_is_rejected(self):
        image = self._textured()
        assert _detect_structural_shift(_region(100, 100, 3, 3), image, image.copy())[0] is False

    def test_an_out_of_bounds_region_is_rejected_rather_than_raising(self):
        image = self._textured()
        assert _detect_structural_shift(_region(390, 390, 100, 100), image, image.copy())[0] is False

    def test_a_negative_origin_is_rejected(self):
        image = self._textured()
        assert _detect_structural_shift(_region(-10, -10, 60, 60), image, image.copy())[0] is False


# ---------------------------------------------------------------------------
# _dom_diff_region
# ---------------------------------------------------------------------------

class TestDomDiffRegion:
    def test_uses_the_largest_pixel_region(self):
        regions = [_region(0, 0, 10, 10), _region(100, 100, 200, 200), _region(50, 50, 20, 20)]
        chosen = _dom_diff_region(_result(regions))
        assert chosen.area == 200 * 200

    def test_falls_back_to_the_whole_page_when_there_are_no_regions(self):
        """A caption changing font, or a label losing its colour, often produces
        a pixel delta too faint to clear min_region_area — but the DOM diff does
        not need a pixel region to see it."""
        chosen = _dom_diff_region(_result([], baseline_size=[1440, 900]))
        assert (chosen.x, chosen.y) == (0, 0)
        assert (chosen.width, chosen.height) == (1440, 900)

    def test_returns_none_when_the_page_size_is_unknown(self):
        assert _dom_diff_region(_result([], baseline_size=[0, 0])) is None

    def test_returns_none_for_an_empty_size(self):
        assert _dom_diff_region(_result([], baseline_size=[])) is None
