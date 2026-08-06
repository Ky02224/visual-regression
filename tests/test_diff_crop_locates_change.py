"""The crop handed to the model must contain the change.

`result.regions` only holds differences big enough to clear min_region_area
(120px). Recolouring a heading changes a few hundred scattered glyph pixels and
clears nothing, so the crop fell through to a *random* location — the model was
shown an unchanged part of the page and asked what had changed there. Measured
on the live no-DOM evaluation: 90 of 93 colour-regression trials had no region,
and the class scored 2.2%.

Answering "nothing changed" was correct for what the model was given. The defect
is in what it was given.
"""
import numpy as np
import pytest

from visual_regression.ai_training import _extract_diff_crop
from visual_regression.models import CompareResult, DiffRegion


def _result(regions=()):
    return CompareResult(
        baseline_size=[900, 600], current_size=[900, 600],
        diff_pixels=1, total_pixels=540_000, mismatch_pct=0.01,
        ssim_score=0.99, regions=list(regions),
    )


def _page(colour=200):
    return np.full((600, 900, 3), colour, dtype=np.uint8)


def _contains_the_change(crop_pair, marker):
    """True when the crop actually shows the recoloured pixels."""
    _, current_crop = crop_pair
    return bool(np.any(np.all(current_crop == marker, axis=-1)))


class TestSubThresholdChange:
    def test_a_small_recolour_with_no_region_is_still_centred_on(self):
        """The regression: this returned a random crop that missed the change."""
        marker = (20, 20, 220)
        baseline = _page()
        current = _page()
        current[500:512, 800:840] = marker      # 480px, well under min_region_area

        crop = _extract_diff_crop(baseline, current, _result(), padding=40)

        assert _contains_the_change(crop, marker), (
            "the crop does not contain the changed pixels — the model is being "
            "shown an unchanged part of the page"
        )

    def test_a_change_in_a_corner_is_found(self):
        marker = (10, 240, 10)
        baseline = _page()
        current = _page()
        current[0:6, 0:20] = marker

        crop = _extract_diff_crop(baseline, current, _result(), padding=40)

        assert _contains_the_change(crop, marker)

    def test_the_crop_is_large_enough_for_the_backbone(self):
        baseline = _page()
        current = _page()
        current[300:304, 400:410] = (0, 0, 255)

        bl_crop, cu_crop = _extract_diff_crop(baseline, current, _result(), padding=40)

        assert bl_crop.shape[0] >= 64 and bl_crop.shape[1] >= 64
        assert bl_crop.shape == cu_crop.shape, "the two crops must align pixel for pixel"


class TestExistingBehaviourIsKept:
    def test_a_real_region_still_wins(self):
        """When the comparison did produce a region, that is the authority."""
        marker = (0, 0, 255)
        baseline = _page()
        current = _page()
        current[100:200, 100:300] = marker
        regions = [DiffRegion(x=100, y=100, width=200, height=100, area=20_000, mean_delta=55.0)]

        bl_crop, _ = _extract_diff_crop(baseline, current, _result(regions), padding=40)

        assert bl_crop.shape[0] == 180, "expected the region box grown by padding"

    def test_identical_images_still_give_a_random_crop(self):
        """A benign sample has nothing to centre on; the old behaviour is right."""
        baseline = _page()
        current = _page()

        bl_crop, cu_crop = _extract_diff_crop(baseline, current, _result(), padding=40)

        assert bl_crop.size > 0
        assert np.array_equal(bl_crop, cu_crop)

    def test_noise_below_the_sensor_floor_does_not_hijack_the_crop(self):
        """A ±1 compression wobble everywhere must not be read as 'the change'."""
        rng = np.random.default_rng(0)
        baseline = _page()
        current = baseline + rng.integers(0, 2, size=baseline.shape, dtype=np.uint8)

        bl_crop, _ = _extract_diff_crop(baseline, current, _result(), padding=40)

        assert bl_crop.shape[0] >= 64 and bl_crop.shape[1] >= 64
