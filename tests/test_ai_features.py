import numpy as np

from visual_regression.ai_features import (
    DEFAULT_IMAGE_SIZE,
    ensure_rgb_batch,
    normalize_batch_uint8,
    diagnose_from_dom_diff,
)
from visual_regression.models import DiffRegion


def test_prepare_and_normalize_backbone_batch():
    image = np.zeros((64, 96, 3), dtype=np.uint8)
    image[:, :] = (10, 20, 30)

    batch = ensure_rgb_batch([image])
    assert batch.shape == (1, DEFAULT_IMAGE_SIZE, DEFAULT_IMAGE_SIZE, 3)
    normalized = normalize_batch_uint8(batch)
    assert normalized.shape == (1, 3, DEFAULT_IMAGE_SIZE, DEFAULT_IMAGE_SIZE)
    assert normalized.dtype == np.float32


def _region(x=100, y=100, w=200, h=50):
    return DiffRegion(x=x, y=y, width=w, height=h, area=w * h, mean_delta=40.0)


def test_dom_diff_detects_missing_element():
    baseline = [{"tag": "button", "x": 110, "y": 110, "w": 100, "h": 30}]
    label, evidence = diagnose_from_dom_diff(baseline, [], _region())
    assert label == "missing-element"
    assert "button" in evidence


def test_dom_diff_allow_missing_false_suppresses_missing_verdict():
    baseline = [{"tag": "button", "x": 110, "y": 110, "w": 100, "h": 30}]
    label, evidence = diagnose_from_dom_diff(baseline, [], _region(), allow_missing=False)
    assert label is None


def test_dom_diff_allow_missing_false_still_trusts_id_identity():
    # A weak (position-only) missing verdict is suppressed without a real
    # pixel region, but a strong one (unique id, globally checked) should
    # still be trusted even in full-page-fallback mode.
    baseline = [{"tag": "button", "x": 110, "y": 110, "w": 100, "h": 30, "eid": "submit-btn"}]
    label, evidence = diagnose_from_dom_diff(baseline, [], _region(), allow_missing=False)
    assert label == "missing-element"


def test_dom_diff_allow_missing_false_still_trusts_text_identity():
    baseline = [{"tag": "a", "x": 110, "y": 110, "w": 100, "h": 30, "txt": "Breaking news story headline"}]
    label, evidence = diagnose_from_dom_diff(baseline, [], _region(), allow_missing=False)
    assert label == "missing-element"


def test_dom_diff_allow_missing_false_lets_weaker_signal_through():
    # A "missing" media element (noise from unrelated page churn, e.g. a
    # full-page fallback scan) should not block a genuine truncation finding
    # on a different, matched element when allow_missing=False.
    baseline = [
        {"tag": "img", "x": 10, "y": 10, "w": 50, "h": 50},
        {"tag": "span", "x": 110, "y": 110, "w": 100, "h": 16, "sw": 100, "cw": 100},
    ]
    current = [
        {"tag": "span", "x": 111, "y": 110, "w": 100, "h": 16, "sw": 260, "cw": 100},
    ]
    label, evidence = diagnose_from_dom_diff(baseline, current, _region(), allow_missing=False)
    assert label == "text-issue"


def test_dom_diff_detects_broken_image_for_media_tags():
    baseline = [{"tag": "img", "x": 110, "y": 110, "w": 100, "h": 30}]
    current = [{"tag": "img", "x": 900, "y": 900, "w": 100, "h": 30}]
    label, evidence = diagnose_from_dom_diff(baseline, current, _region())
    assert label == "broken-image"


def test_dom_diff_keeps_broken_image_when_a_sibling_survives():
    # Only the image was removed. Its container's box collapses around the hole,
    # so the container fails to match and looks "missing" too — the exact shape
    # that geometric containment misread. The surviving caption is the tell: a
    # genuinely removed container would have taken it as well.
    baseline = [
        {"tag": "div", "x": 100, "y": 100, "w": 220, "h": 140, "eid": "thumb-box"},
        {"tag": "img", "x": 110, "y": 110, "w": 100, "h": 60},
        {"tag": "span", "x": 110, "y": 180, "w": 180, "h": 20,
         "txt": "Quarterly results are published"},
    ]
    current = [
        {"tag": "span", "x": 110, "y": 120, "w": 180, "h": 20,
         "txt": "Quarterly results are published"},
    ]
    label, evidence = diagnose_from_dom_diff(baseline, current, _region())
    assert label == "broken-image"
    assert "img" in evidence


def test_dom_diff_matches_by_id_despite_ambiguous_geometry():
    # Two same-tag, similar-size elements near each other post-reflow — pure
    # geometry matching could pair either one, but a shared id disambiguates.
    baseline = [
        {"tag": "span", "eid": "price-tag", "x": 110, "y": 110, "w": 80, "h": 20, "color": "rgb(0,0,0)"},
        {"tag": "span", "x": 150, "y": 112, "w": 80, "h": 20, "color": "rgb(0,0,0)"},
    ]
    current = [
        {"tag": "span", "x": 150, "y": 112, "w": 80, "h": 20, "color": "rgb(0,0,0)"},
        {"tag": "span", "eid": "price-tag", "x": 112, "y": 110, "w": 80, "h": 20, "color": "rgb(220,20,20)"},
    ]
    label, evidence = diagnose_from_dom_diff(baseline, current, _region())
    assert label == "color-regression"
    assert "text color" in evidence


def test_dom_diff_text_identity_survives_list_reflow():
    # Removing item 1 from a 3-item list reflows items 2 and 3 up by one
    # slot each. Position-based matching would pair "item 2" (now sitting
    # where "item 1" used to be) with the removed item and call it "moved".
    # Text-based identity should instead correctly identify item 1 as gone.
    baseline = [
        {"tag": "a", "x": 100, "y": 100, "w": 200, "h": 20, "txt": "Breaking news story one headline"},
        {"tag": "a", "x": 100, "y": 130, "w": 200, "h": 20, "txt": "Second unrelated story headline"},
        {"tag": "a", "x": 100, "y": 160, "w": 200, "h": 20, "txt": "Third completely different story"},
    ]
    current = [
        {"tag": "a", "x": 100, "y": 100, "w": 200, "h": 20, "txt": "Second unrelated story headline"},
        {"tag": "a", "x": 100, "y": 130, "w": 200, "h": 20, "txt": "Third completely different story"},
    ]
    label, evidence = diagnose_from_dom_diff(baseline, current, _region(y=100, h=100))
    assert label == "missing-element"


def test_dom_diff_text_identity_ignores_short_or_duplicate_text():
    # Text under the length floor, or duplicated across candidates, must not
    # be trusted as an identity match — falls through to geometry instead.
    baseline = [{"tag": "a", "x": 110, "y": 110, "w": 80, "h": 20, "txt": "More"}]
    current = [
        {"tag": "a", "x": 400, "y": 400, "w": 80, "h": 20, "txt": "More"},
        {"tag": "a", "x": 112, "y": 110, "w": 80, "h": 20, "txt": "More"},
    ]
    label, evidence = diagnose_from_dom_diff(baseline, current, _region())
    # Should not blindly text-match to the far-away duplicate; nearest-geometry wins instead.
    assert label is None


def test_dom_diff_detects_layout_shift():
    baseline = [{"tag": "p", "x": 110, "y": 110, "w": 100, "h": 30}]
    current = [{"tag": "p", "x": 160, "y": 110, "w": 100, "h": 30}]
    label, evidence = diagnose_from_dom_diff(baseline, current, _region())
    assert label == "layout-issue"


def test_dom_diff_detects_font_change():
    baseline = [{"tag": "p", "x": 110, "y": 110, "w": 100, "h": 30, "font": "Arial"}]
    current = [{"tag": "p", "x": 112, "y": 110, "w": 100, "h": 30, "font": "Courier New"}]
    label, evidence = diagnose_from_dom_diff(baseline, current, _region())
    assert label == "font-change"


def test_dom_diff_detects_text_color_regression():
    baseline = [{"tag": "p", "x": 110, "y": 110, "w": 100, "h": 30, "color": "rgb(20, 20, 20)"}]
    current = [{"tag": "p", "x": 111, "y": 110, "w": 100, "h": 30, "color": "rgb(220, 20, 20)"}]
    label, evidence = diagnose_from_dom_diff(baseline, current, _region())
    assert label == "color-regression"
    assert "text color" in evidence


def test_dom_diff_detects_background_color_regression():
    baseline = [{"tag": "button", "x": 110, "y": 110, "w": 100, "h": 30, "bg": "rgb(240, 240, 240)"}]
    current = [{"tag": "button", "x": 111, "y": 110, "w": 100, "h": 30, "bg": "rgb(10, 10, 10)"}]
    label, evidence = diagnose_from_dom_diff(baseline, current, _region())
    assert label == "color-regression"
    assert "background color" in evidence


def test_dom_diff_detects_new_text_truncation():
    baseline = [{"tag": "p", "x": 110, "y": 110, "w": 100, "h": 30, "sw": 100, "cw": 100}]
    current = [{"tag": "p", "x": 110, "y": 110, "w": 100, "h": 30, "sw": 260, "cw": 100}]
    label, evidence = diagnose_from_dom_diff(baseline, current, _region())
    assert label == "text-issue"
    assert "overflow" in evidence


def test_dom_diff_ignores_preexisting_truncation():
    baseline = [{"tag": "p", "x": 110, "y": 110, "w": 100, "h": 30, "sw": 260, "cw": 100}]
    current = [{"tag": "p", "x": 111, "y": 110, "w": 100, "h": 30, "sw": 260, "cw": 100}]
    label, evidence = diagnose_from_dom_diff(baseline, current, _region())
    assert label is None


def test_dom_diff_detects_contrast_collapse_as_text_issue():
    baseline = [{"tag": "p", "x": 110, "y": 110, "w": 100, "h": 30, "color": "rgb(0, 0, 0)", "bg": "rgb(255, 255, 255)"}]
    current = [{"tag": "p", "x": 111, "y": 110, "w": 100, "h": 30, "color": "rgb(235, 235, 235)", "bg": "rgb(255, 255, 255)"}]
    label, evidence = diagnose_from_dom_diff(baseline, current, _region())
    assert label == "text-issue"
    assert "contrast" in evidence


def test_dom_diff_ignores_transparent_color_noise():
    baseline = [{"tag": "p", "x": 110, "y": 110, "w": 100, "h": 30, "bg": "rgba(0, 0, 0, 0)"}]
    current = [{"tag": "p", "x": 111, "y": 110, "w": 100, "h": 30, "bg": "rgba(0, 0, 0, 0)"}]
    label, evidence = diagnose_from_dom_diff(baseline, current, _region())
    assert label is None


def test_dom_diff_returns_none_when_elements_match_closely():
    baseline = [{"tag": "p", "x": 110, "y": 110, "w": 100, "h": 30, "font": "Arial"}]
    current = [{"tag": "p", "x": 111, "y": 110, "w": 100, "h": 30, "font": "Arial"}]
    label, evidence = diagnose_from_dom_diff(baseline, current, _region())
    assert label is None
    assert evidence == ""


def test_dom_diff_returns_none_with_no_elements_near_region():
    assert diagnose_from_dom_diff([], [], _region()) == (None, "")


def test_dom_diff_match_is_exclusive_across_baseline_elements():
    # Two baseline images stacked vertically; the top one is removed, and
    # the bottom one shifts up to fill the gap. Matched independently and
    # greedily, BOTH baseline images end up picking the same surviving
    # current image as their "nearest" candidate (the removed one is even
    # geometrically closer to it than the survivor is, post-reflow) — so
    # neither is reported missing and the real removal vanishes entirely.
    # Each current element must only be claimable by one baseline element.
    baseline = [
        {"tag": "img", "x": 84, "y": 14, "w": 140, "h": 22},
        {"tag": "img", "x": 84, "y": 41, "w": 140, "h": 11},
    ]
    current = [{"tag": "img", "x": 84, "y": 22, "w": 140, "h": 11}]
    label, evidence = diagnose_from_dom_diff(
        baseline, current, _region(x=0, y=0, w=300, h=100)
    )
    assert label == "broken-image"
    assert "img" in evidence


def test_dom_diff_broken_image_not_masked_by_reflowed_sibling():
    # Removing an <img> frees vertical space, so a sibling <div> below it
    # reflows upward — a real, but purely downstream, side effect. The img
    # itself has no id/text (media tags never capture text), but it's still
    # the actual root cause and must win over the sibling's "moved" verdict,
    # not get out-prioritized by it.
    baseline = [
        {"tag": "img", "x": 44, "y": 90, "w": 200, "h": 60},
        {"tag": "div", "x": 44, "y": 160, "w": 200, "h": 40},
    ]
    current = [
        {"tag": "div", "x": 44, "y": 95, "w": 200, "h": 40},
    ]
    label, evidence = diagnose_from_dom_diff(baseline, current, _region(x=44, y=90, w=200, h=110))
    assert label == "broken-image"
    assert "img" in evidence
