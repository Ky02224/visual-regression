"""compare_arrays used to fill an ignored region with each image's own
dominant background color independently (bg_base for the baseline canvas,
bg_current for the current canvas). Whenever those two colors differ — which
happens often, since it's a per-image heuristic and even a legitimate,
unrelated change elsewhere on the page can shift which color is "dominant"
— the filled rectangle ends up two different solid colors, and that
difference itself gets counted as a mismatch, defeating the entire purpose
of marking the region as ignored.
"""
import numpy as np

from visual_regression.image_compare import compare_arrays


def test_ignore_region_does_not_register_a_diff_when_backgrounds_differ():
    height, width = 200, 200
    # Baseline: light background everywhere.
    baseline = np.full((height, width, 3), 240, dtype=np.uint8)
    # Current: same light background, EXCEPT a large solid dark block placed
    # so it dominates the "current" image's background-color heuristic —
    # this is exactly the scenario that used to make bg_base != bg_current.
    current = np.full((height, width, 3), 240, dtype=np.uint8)
    current[:, :] = 30  # current is now mostly dark everywhere

    # Ignore nearly the whole frame, leaving no un-ignored area that could
    # register a genuine diff on its own.
    ignore_regions = [(0, 0, width, height)]

    result, _, _ = compare_arrays(
        baseline=baseline,
        current=current,
        pixel_threshold=10,
        min_region_area=20,
        ignore_regions=ignore_regions,
    )

    assert result.mismatch_pct == 0.0
    assert result.diff_pixels == 0
