"""Tests for image_compare's internal helpers.

test_image_compare.py covers compare_arrays end to end. These cover the pieces
underneath it that decide what the top-level numbers mean:

* `parse_ignore_regions` turns CLI/API strings into the rectangles the diff
  ignores. Accept a malformed one silently and the user's masked area is not
  actually masked.
* `_normalize_canvas` decides what happens when a page grew or shrank between
  captures — the padding colour it picks becomes real diff pixels if wrong.
* `_apply_ignore_regions` fills with each image's own background so masking a
  dark-theme UI does not itself register as a change.
* `_merge_nearby_regions` collapses fragments into one region, which is what
  `region_count` — an AI rule feature and a severity input — ends up counting.
"""

from __future__ import annotations

import numpy as np
import pytest

from visual_regression.image_compare import (
    _apply_ignore_regions,
    _get_dominant_background_color,
    _merge_nearby_regions,
    _normalize_canvas,
    compare_arrays,
    parse_ignore_regions,
)
from visual_regression.models import DiffRegion


# ---------------------------------------------------------------------------
# parse_ignore_regions
# ---------------------------------------------------------------------------

class TestParseIgnoreRegions:
    def test_parses_one_region(self):
        assert parse_ignore_regions(["10,20,30,40"]) == [(10, 20, 30, 40)]

    def test_parses_several(self):
        assert parse_ignore_regions(["0,0,5,5", "10,10,20,20"]) == [(0, 0, 5, 5), (10, 10, 20, 20)]

    def test_tolerates_surrounding_whitespace(self):
        assert parse_ignore_regions([" 1 , 2 , 3 , 4 "]) == [(1, 2, 3, 4)]

    def test_empty_input_gives_no_regions(self):
        assert parse_ignore_regions([]) == []

    @pytest.mark.parametrize("raw", ["1,2,3", "1,2,3,4,5", "", "1"])
    def test_rejects_the_wrong_number_of_values(self, raw):
        with pytest.raises(ValueError, match="Expected x,y,width,height"):
            parse_ignore_regions([raw])

    @pytest.mark.parametrize("raw", ["0,0,0,10", "0,0,10,0", "0,0,-5,10"])
    def test_rejects_a_region_with_no_area(self, raw):
        """A zero-area rectangle masks nothing; accepting it silently would let
        a user believe an area was excluded when it was not."""
        with pytest.raises(ValueError, match="width/height must be > 0"):
            parse_ignore_regions([raw])

    def test_rejects_non_numeric_values(self):
        with pytest.raises(ValueError):
            parse_ignore_regions(["a,b,c,d"])

    def test_allows_a_negative_origin(self):
        """A region may start off-canvas; clipping is the filler's job."""
        assert parse_ignore_regions(["-5,-5,20,20"]) == [(-5, -5, 20, 20)]


# ---------------------------------------------------------------------------
# Background colour
# ---------------------------------------------------------------------------

class TestDominantBackgroundColour:
    def test_reads_a_uniform_image(self):
        assert _get_dominant_background_color(np.full((10, 10, 3), 40, dtype=np.uint8)) == (40, 40, 40)

    def test_samples_the_corners_not_the_centre(self):
        """Page chrome lives at the edges; a big central hero image should not
        decide the padding colour."""
        image = np.full((20, 20, 3), 250, dtype=np.uint8)
        image[5:15, 5:15] = 0
        assert _get_dominant_background_color(image) == (250, 250, 250)

    def test_falls_back_to_white_for_an_empty_image(self):
        assert _get_dominant_background_color(np.zeros((0, 0, 3), dtype=np.uint8)) == (255, 255, 255)


# ---------------------------------------------------------------------------
# Canvas normalisation
# ---------------------------------------------------------------------------

class TestNormalizeCanvas:
    def test_pads_both_images_to_the_larger_bounds(self):
        small = np.full((10, 10, 3), 100, dtype=np.uint8)
        large = np.full((30, 20, 3), 100, dtype=np.uint8)

        canvas_a, canvas_b, _, _ = _normalize_canvas(small, large)

        assert canvas_a.shape == canvas_b.shape == (30, 20, 3)

    def test_leaves_equal_sized_images_untouched(self):
        a = np.full((10, 10, 3), 10, dtype=np.uint8)
        b = np.full((10, 10, 3), 200, dtype=np.uint8)

        canvas_a, canvas_b, _, _ = _normalize_canvas(a, b)

        assert np.array_equal(canvas_a, a)
        assert np.array_equal(canvas_b, b)

    def test_original_content_is_preserved_top_left(self):
        small = np.full((5, 5, 3), 77, dtype=np.uint8)
        large = np.full((10, 10, 3), 200, dtype=np.uint8)

        canvas_a, _, _, _ = _normalize_canvas(small, large)

        assert np.all(canvas_a[0:5, 0:5] == 77)

    def test_each_image_is_padded_with_its_own_background(self):
        """Padding a dark page with white would make the padding itself the
        largest 'change' in the diff."""
        dark = np.full((5, 5, 3), 12, dtype=np.uint8)
        light = np.full((10, 10, 3), 240, dtype=np.uint8)

        canvas_a, canvas_b, bg_a, bg_b = _normalize_canvas(dark, light)

        assert bg_a == (12, 12, 12)
        assert bg_b == (240, 240, 240)
        assert tuple(canvas_a[9, 9]) == (12, 12, 12)
        assert tuple(canvas_b[9, 9]) == (240, 240, 240)


# ---------------------------------------------------------------------------
# Ignore-region filling
# ---------------------------------------------------------------------------

class TestApplyIgnoreRegions:
    def test_fills_the_requested_rectangle(self):
        image = np.zeros((20, 20, 3), dtype=np.uint8)
        _apply_ignore_regions(image, [(5, 5, 10, 10)], fill_color=(255, 255, 255))
        assert np.all(image[5:15, 5:15] == 255)

    def test_leaves_everything_outside_alone(self):
        image = np.zeros((20, 20, 3), dtype=np.uint8)
        _apply_ignore_regions(image, [(5, 5, 5, 5)], fill_color=(255, 255, 255))
        assert np.all(image[0:5, 0:5] == 0)
        assert np.all(image[15:20, 15:20] == 0)

    def test_clips_a_region_that_starts_off_canvas(self):
        image = np.zeros((20, 20, 3), dtype=np.uint8)
        _apply_ignore_regions(image, [(-10, -10, 15, 15)], fill_color=(255, 255, 255))
        assert np.all(image[0:5, 0:5] == 255)

    def test_clips_a_region_that_runs_past_the_edge(self):
        image = np.zeros((20, 20, 3), dtype=np.uint8)
        _apply_ignore_regions(image, [(15, 15, 100, 100)], fill_color=(255, 255, 255))
        assert np.all(image[15:20, 15:20] == 255)

    def test_a_fully_off_canvas_region_is_a_no_op(self):
        image = np.zeros((20, 20, 3), dtype=np.uint8)
        _apply_ignore_regions(image, [(100, 100, 10, 10)], fill_color=(255, 255, 255))
        assert np.all(image == 0)

    def test_masking_removes_a_difference_from_the_comparison(self):
        """The end-to-end property the feature exists for."""
        baseline = np.full((40, 40, 3), 200, dtype=np.uint8)
        current = baseline.copy()
        current[10:20, 10:20] = 0

        without, _, _ = compare_arrays(
            baseline=baseline, current=current, pixel_threshold=20,
            min_region_area=4, ignore_regions=[],
        )
        with_mask, _, _ = compare_arrays(
            baseline=baseline, current=current, pixel_threshold=20,
            min_region_area=4, ignore_regions=[(8, 8, 15, 15)],
        )

        assert without.mismatch_pct > 0
        assert with_mask.mismatch_pct == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Region merging — feeds region_count, an AI feature and a severity input
# ---------------------------------------------------------------------------

def _region(x, y, w, h, area=None, delta=10.0):
    return DiffRegion(x=x, y=y, width=w, height=h, area=area if area is not None else w * h, mean_delta=delta)


class TestMergeNearbyRegions:
    def test_an_empty_list_is_returned_unchanged(self):
        assert _merge_nearby_regions([]) == []

    def test_a_single_region_is_returned_unchanged(self):
        regions = [_region(0, 0, 10, 10)]
        assert _merge_nearby_regions(regions) == regions

    def test_adjacent_regions_merge_into_one(self):
        merged = _merge_nearby_regions([_region(0, 0, 10, 10), _region(15, 0, 10, 10)], merge_gap=20)
        assert len(merged) == 1

    def test_distant_regions_stay_separate(self):
        merged = _merge_nearby_regions([_region(0, 0, 10, 10), _region(500, 500, 10, 10)], merge_gap=20)
        assert len(merged) == 2

    def test_the_merged_box_covers_both_originals(self):
        merged = _merge_nearby_regions([_region(0, 0, 10, 10), _region(15, 5, 10, 10)], merge_gap=20)[0]
        assert merged.x == 0
        assert merged.y == 0
        assert merged.x + merged.width >= 25
        assert merged.y + merged.height >= 15

    def test_areas_are_summed_not_recomputed_from_the_box(self):
        """The bounding box of two small distant-ish regions is mostly empty;
        using its area would overstate how much of the page changed."""
        merged = _merge_nearby_regions([_region(0, 0, 10, 10), _region(15, 0, 10, 10)], merge_gap=20)[0]
        assert merged.area == 200

    def test_mean_delta_is_weighted_by_area(self):
        merged = _merge_nearby_regions(
            [_region(0, 0, 10, 10, area=100, delta=10.0), _region(12, 0, 10, 10, area=300, delta=20.0)],
            merge_gap=20,
        )[0]
        assert merged.mean_delta == pytest.approx(17.5, abs=0.01)

    def test_merging_is_transitive_across_a_chain(self):
        """A merges with B and B with C, so all three become one even though A
        and C are further apart than the gap."""
        chain = [_region(0, 0, 10, 10), _region(15, 0, 10, 10), _region(30, 0, 10, 10)]
        assert len(_merge_nearby_regions(chain, merge_gap=10)) == 1

    def test_a_zero_gap_merges_only_overlapping_regions(self):
        separate = [_region(0, 0, 10, 10), _region(50, 50, 10, 10)]
        assert len(_merge_nearby_regions(separate, merge_gap=0)) == 2
