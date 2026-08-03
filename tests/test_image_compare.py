"""Unit tests for the core pixel-diffing algorithm in visual_regression.image_compare.

These tests exercise the real comparison logic (compare_arrays / compare_images /
parse_ignore_regions) against small synthetic numpy images rather than mocking any
part of the algorithm, since pass/fail verdicts across the whole product flow from
this module.
"""
from pathlib import Path

import cv2
import numpy as np
import pytest

from visual_regression.image_compare import (
    compare_arrays,
    compare_arrays_batch,
    compare_images,
    parse_ignore_regions,
)


def _flat_image(height: int, width: int, color: int) -> np.ndarray:
    """A flat BGR image of a single gray value (mirrors what cv2.imread returns)."""
    return np.full((height, width, 3), color, dtype=np.uint8)


def _image_with_patch(
    height: int,
    width: int,
    bg_color: int,
    patch_color: int,
    patch_box: tuple[int, int, int, int],
) -> np.ndarray:
    """A flat background image with a solid rectangular patch drawn on it.

    patch_box is (x, y, w, h) in image (col, row) coordinates.
    """
    img = _flat_image(height, width, bg_color)
    x, y, w, h = patch_box
    img[y : y + h, x : x + w] = patch_color
    return img


# ---------------------------------------------------------------------------
# Identical images
# ---------------------------------------------------------------------------


def test_identical_images_produce_zero_mismatch():
    img = _flat_image(64, 64, 180)

    result, overlay, binary = compare_arrays(
        baseline=img,
        current=img.copy(),
        pixel_threshold=20,
        min_region_area=20,
        ignore_regions=[],
    )

    assert result.diff_pixels == 0
    assert result.mismatch_pct == 0.0
    assert result.regions == []
    assert result.ssim_score == 1.0
    assert int(np.count_nonzero(binary)) == 0
    # Overlay should be untouched (identical to the current image) since no pixels differ.
    assert np.array_equal(overlay, img)


def test_identical_images_with_patch_pattern_still_zero_diff():
    # Not perfectly flat (has internal structure/edges) to make sure identical
    # non-trivial images also produce zero mismatch, not just flat colors.
    img = _image_with_patch(80, 80, bg_color=200, patch_color=40, patch_box=(10, 10, 20, 20))

    result, _, _ = compare_arrays(
        baseline=img,
        current=img.copy(),
        pixel_threshold=20,
        min_region_area=20,
        ignore_regions=[],
    )

    assert result.diff_pixels == 0
    assert result.mismatch_pct == 0.0
    assert result.regions == []


# ---------------------------------------------------------------------------
# Known diff region detection
# ---------------------------------------------------------------------------


def test_diff_region_is_detected_with_matching_coordinates():
    height, width = 100, 100
    baseline = _flat_image(height, width, 220)
    patch_box = (30, 40, 25, 20)  # x, y, w, h
    current = _image_with_patch(height, width, bg_color=220, patch_color=20, patch_box=patch_box)

    result, overlay, binary = compare_arrays(
        baseline=baseline,
        current=current,
        pixel_threshold=20,
        min_region_area=20,
        ignore_regions=[],
    )

    assert result.diff_pixels > 0
    assert result.mismatch_pct > 0
    assert len(result.regions) >= 1

    px, py, pw, ph = patch_box
    # At least one detected region should roughly overlap the drawn patch.
    region = result.regions[0]
    assert region.x <= px + pw
    assert region.x + region.width >= px
    assert region.y <= py + ph
    assert region.y + region.height >= py
    assert region.area > 0
    assert region.mean_delta > 0

    # The overlay should be tinted (different from the plain current image) in
    # the area that changed.
    assert not np.array_equal(overlay, current)


def test_larger_diff_produces_larger_mismatch_percentage():
    height, width = 100, 100
    baseline = _flat_image(height, width, 220)
    small_current = _image_with_patch(height, width, 220, 20, (10, 10, 10, 10))
    large_current = _image_with_patch(height, width, 220, 20, (10, 10, 40, 40))

    small_result, _, _ = compare_arrays(
        baseline=baseline,
        current=small_current,
        pixel_threshold=20,
        min_region_area=5,
        ignore_regions=[],
    )
    large_result, _, _ = compare_arrays(
        baseline=baseline,
        current=large_current,
        pixel_threshold=20,
        min_region_area=5,
        ignore_regions=[],
    )

    assert large_result.mismatch_pct > small_result.mismatch_pct
    assert large_result.diff_pixels > small_result.diff_pixels


# ---------------------------------------------------------------------------
# Ignore-region masking
# ---------------------------------------------------------------------------


def test_diff_fully_inside_ignore_region_is_not_counted():
    height, width = 100, 100
    baseline = _flat_image(height, width, 220)
    patch_box = (30, 40, 20, 20)
    current = _image_with_patch(height, width, 220, 20, patch_box)

    # Ignore region generously covers the patch.
    ignore_regions = [(20, 30, 40, 40)]

    result, _, _ = compare_arrays(
        baseline=baseline,
        current=current,
        pixel_threshold=20,
        min_region_area=20,
        ignore_regions=ignore_regions,
    )

    assert result.diff_pixels == 0
    assert result.mismatch_pct == 0.0
    assert result.regions == []


def test_diff_outside_ignore_region_is_still_detected():
    height, width = 100, 100
    baseline = _flat_image(height, width, 220)
    patch_box = (30, 40, 20, 20)
    current = _image_with_patch(height, width, 220, 20, patch_box)

    # Ignore region far away from the actual diff -- should have no masking effect.
    ignore_regions = [(0, 0, 10, 10)]

    result, _, _ = compare_arrays(
        baseline=baseline,
        current=current,
        pixel_threshold=20,
        min_region_area=20,
        ignore_regions=ignore_regions,
    )

    assert result.diff_pixels > 0
    assert result.mismatch_pct > 0
    assert len(result.regions) >= 1


def test_ignore_region_with_differing_backgrounds_masks_diff():
    # Regression coverage for the documented behavior in test_ignore_region_fill.py:
    # ignoring a region must not itself register as a diff, even when the two
    # images' dominant background colors differ.
    height, width = 120, 120
    baseline = _flat_image(height, width, 240)
    current = _flat_image(height, width, 30)

    ignore_regions = [(0, 0, width, height)]

    result, _, _ = compare_arrays(
        baseline=baseline,
        current=current,
        pixel_threshold=10,
        min_region_area=20,
        ignore_regions=ignore_regions,
    )

    assert result.diff_pixels == 0
    assert result.mismatch_pct == 0.0


# ---------------------------------------------------------------------------
# Mismatched image dimensions
# ---------------------------------------------------------------------------


def test_compare_arrays_pads_mismatched_dimensions_instead_of_raising():
    baseline = _flat_image(40, 60, 200)   # height=40, width=60
    current = _flat_image(60, 80, 200)    # height=60, width=80

    result, overlay, binary = compare_arrays(
        baseline=baseline,
        current=current,
        pixel_threshold=20,
        min_region_area=20,
        ignore_regions=[],
    )

    # Canvases are normalized to the max dimensions of the two inputs, so both
    # reported sizes end up equal (width, height order per CompareResult).
    assert result.baseline_size == [80, 60]
    assert result.current_size == [80, 60]
    assert overlay.shape[:2] == (60, 80)
    assert binary.shape[:2] == (60, 80)
    # Same fill color on both sides of the padded area (both flat 200) -> no
    # spurious diff from padding itself.
    assert result.diff_pixels == 0


def test_compare_images_warns_on_dimension_mismatch(tmp_path: Path, capsys):
    baseline_path = tmp_path / "baseline.png"
    current_path = tmp_path / "current.png"
    cv2.imwrite(str(baseline_path), _flat_image(40, 40, 210))
    cv2.imwrite(str(current_path), _flat_image(60, 60, 210))

    result, _, _ = compare_images(
        baseline_path=baseline_path,
        current_path=current_path,
        pixel_threshold=20,
        min_region_area=20,
        ignore_regions=[],
    )

    captured = capsys.readouterr()
    assert "dimension mismatch" in captured.out.lower()
    assert result.baseline_size == [60, 60]
    assert result.current_size == [60, 60]


# ---------------------------------------------------------------------------
# Edge cases: maximal difference / alpha channel
# ---------------------------------------------------------------------------


def test_all_black_vs_all_white_is_near_total_mismatch():
    height, width = 64, 64
    black = _flat_image(height, width, 0)
    white = _flat_image(height, width, 255)

    result, _, binary = compare_arrays(
        baseline=black,
        current=white,
        pixel_threshold=20,
        min_region_area=20,
        ignore_regions=[],
    )

    assert result.mismatch_pct > 95.0
    assert result.diff_pixels > 0
    # Virtually the whole binary mask should be flagged as different.
    assert int(np.count_nonzero(binary)) == result.diff_pixels
    assert len(result.regions) >= 1


def test_rgba_input_raises_instead_of_silently_misbehaving():
    # image_compare works exclusively with 3-channel BGR arrays (as produced by
    # cv2.imread(..., cv2.IMREAD_COLOR)). Feeding it 4-channel (BGRA) arrays is
    # not a supported path -- it should fail loudly (shape mismatch) rather
    # than silently produce a bogus comparison.
    height, width = 40, 40
    baseline_rgba = np.full((height, width, 4), 200, dtype=np.uint8)
    current_rgba = np.full((height, width, 4), 200, dtype=np.uint8)

    # Naming the type and message pins down WHICH failure this is: a bare
    # `pytest.raises(Exception)` would also pass if the call started failing for
    # an unrelated reason, e.g. a typo in the keyword arguments below.
    with pytest.raises(ValueError, match="could not broadcast input array"):
        compare_arrays(
            baseline=baseline_rgba,
            current=current_rgba,
            pixel_threshold=20,
            min_region_area=20,
            ignore_regions=[],
        )


# ---------------------------------------------------------------------------
# Threshold parameters
# ---------------------------------------------------------------------------


def test_pixel_threshold_excludes_subtle_diff_below_threshold():
    height, width = 50, 50
    baseline = _flat_image(height, width, 100)
    current = _flat_image(height, width, 105)  # uniform delta of 5, no edges anywhere

    result, _, _ = compare_arrays(
        baseline=baseline,
        current=current,
        pixel_threshold=20,  # threshold well above the delta of 5
        min_region_area=20,
        ignore_regions=[],
    )

    assert result.diff_pixels == 0
    assert result.mismatch_pct == 0.0


def test_pixel_threshold_includes_diff_above_threshold():
    height, width = 50, 50
    baseline = _flat_image(height, width, 100)
    current = _flat_image(height, width, 105)  # same uniform delta of 5

    result, _, _ = compare_arrays(
        baseline=baseline,
        current=current,
        pixel_threshold=2,  # threshold below the delta of 5
        min_region_area=20,
        ignore_regions=[],
    )

    assert result.diff_pixels > 0
    assert result.mismatch_pct > 0


def test_min_region_area_filters_small_regions_from_list_but_not_from_mismatch_pct():
    height, width = 100, 100
    baseline = _flat_image(height, width, 200)
    # A small isolated patch, away from edges so it survives the 3x3
    # morphological open/dilate passes.
    current = _image_with_patch(height, width, 200, 0, (50, 50, 8, 8))

    small_area_result, _, _ = compare_arrays(
        baseline=baseline,
        current=current,
        pixel_threshold=20,
        min_region_area=5,
        ignore_regions=[],
    )
    large_area_result, _, _ = compare_arrays(
        baseline=baseline,
        current=current,
        pixel_threshold=20,
        min_region_area=5000,
        ignore_regions=[],
    )

    # Same binary mask underneath -> identical mismatch_pct/diff_pixels
    # regardless of min_region_area, since that threshold only prunes the
    # human-facing region list.
    assert small_area_result.diff_pixels == large_area_result.diff_pixels
    assert small_area_result.mismatch_pct == large_area_result.mismatch_pct
    assert small_area_result.diff_pixels > 0

    assert len(small_area_result.regions) >= 1
    assert large_area_result.regions == []


# ---------------------------------------------------------------------------
# parse_ignore_regions
# ---------------------------------------------------------------------------


def test_parse_ignore_regions_valid_input():
    parsed = parse_ignore_regions(["10,20,30,40", "0,0,5,5"])
    assert parsed == [(10, 20, 30, 40), (0, 0, 5, 5)]


def test_parse_ignore_regions_rejects_wrong_field_count():
    with pytest.raises(ValueError):
        parse_ignore_regions(["10,20,30"])


def test_parse_ignore_regions_rejects_non_positive_dimensions():
    with pytest.raises(ValueError):
        parse_ignore_regions(["10,20,0,40"])
    with pytest.raises(ValueError):
        parse_ignore_regions(["10,20,30,-5"])


# ---------------------------------------------------------------------------
# Batch comparison sanity checks
# ---------------------------------------------------------------------------


def test_compare_arrays_batch_mismatched_lengths_raises():
    with pytest.raises(ValueError):
        compare_arrays_batch(
            baselines=[_flat_image(10, 10, 100)],
            currents=[_flat_image(10, 10, 100), _flat_image(10, 10, 100)],
        )


def test_compare_arrays_batch_empty_returns_empty_list():
    assert compare_arrays_batch(baselines=[], currents=[]) == []
