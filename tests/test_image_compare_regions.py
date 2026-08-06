"""Ignore regions stored on a baseline must survive a malformed neighbour."""
from __future__ import annotations

from visual_regression.image_compare import ignore_regions_from_metadata


def test_one_bad_region_does_not_discard_the_others():
    # The parse used to run inside a single try/except, so a malformed entry
    # aborted the loop and every region after it was lost. The comparison then
    # ran with some or none of the areas the reviewer had excluded and reported
    # a difference inside one of them, which reads as a real defect.
    saved = [
        {"x": 10, "y": 20, "width": 100, "height": 50},
        {"x": 0, "y": 0, "width": "not-a-number", "height": 10},   # malformed
        {"x": 200, "y": 300, "width": 40, "height": 40},           # after the bad one
    ]
    regions = ignore_regions_from_metadata(saved, "demo-home")
    assert regions == [(10, 20, 100, 50), (200, 300, 40, 40)]


def test_list_form_and_dict_form_are_both_accepted():
    regions = ignore_regions_from_metadata(
        [[1, 2, 3, 4], {"x": 5, "y": 6, "width": 7, "height": 8}], "demo"
    )
    assert regions == [(1, 2, 3, 4), (5, 6, 7, 8)]


def test_zero_sized_regions_are_dropped():
    # A zero-width region excludes nothing and would mask nothing; keeping it
    # only invites a divide-by-zero deeper in the masking code.
    regions = ignore_regions_from_metadata(
        [{"x": 1, "y": 1, "width": 0, "height": 10}, [2, 2, 5, 5]], "demo"
    )
    assert regions == [(2, 2, 5, 5)]


def test_missing_or_wrong_shaped_metadata_yields_no_regions():
    assert ignore_regions_from_metadata(None, "demo") == []
    assert ignore_regions_from_metadata("nonsense", "demo") == []
    assert ignore_regions_from_metadata([{"x": 1}], "demo") == []
