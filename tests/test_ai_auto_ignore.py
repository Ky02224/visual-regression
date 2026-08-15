"""What the auto-ignore suggester is allowed to propose masking.

The distinction it has to get right is dynamic content (an ad, a clock) versus
a change that simply has not been fixed yet. Both repeat across runs; only the
first renders something different each time. Getting it wrong in the permissive
direction is the expensive mistake — a suggestion that is accepted switches the
case off for every future run, defect included.
"""

import json

import cv2
import numpy as np
import pytest

from visual_regression.ai_auto_ignore import analyze_repeating_regions, get_auto_ignore_suggestions
from visual_regression.config import WorkspacePaths
from visual_regression.database import get_store

PAGE_W, PAGE_H = 400, 300
WIDGET = (40, 50, 120, 60)  # x, y, w, h


@pytest.fixture
def workspace(tmp_path):
    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    paths.ensure()
    store = get_store(paths.db_path)
    return paths, store


def _page(fill_widget_with: int | None) -> np.ndarray:
    """A plain page, optionally with something drawn in the widget slot."""
    img = np.full((PAGE_H, PAGE_W, 3), 240, dtype=np.uint8)
    if fill_widget_with is not None:
        x, y, w, h = WIDGET
        rng = np.random.default_rng(fill_widget_with)
        img[y:y + h, x:x + w] = rng.integers(0, 255, size=(h, w, 3), dtype=np.uint8)
    return img


def _add_run(paths, store, run_id: str, baseline: str, boxes, image: np.ndarray, status: str = "FAIL"):
    store.upsert_run_index({
        "run": run_id,
        "case_name": baseline,
        "baseline_name": baseline,
        "status": status,
        "browser": "chromium",
        "device": "desktop",
    })
    run_dir = paths.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": run_id,
        "baseline_name": baseline,
        "case_name": baseline,
        "status": status,
        "result": {
            "current_size": [PAGE_W, PAGE_H],
            "regions": [{"x": b[0], "y": b[1], "width": b[2], "height": b[3]} for b in boxes],
        },
    }
    (run_dir / "result.json").write_text(json.dumps(payload), encoding="utf-8")
    cv2.imwrite(str(run_dir / "current.png"), image)


def test_content_that_differs_every_run_is_suggested(workspace):
    """An ad slot: same place every run, different pixels every run."""
    paths, store = workspace
    for i in range(4):
        _add_run(paths, store, f"ad-{i}", "ads", [WIDGET], _page(fill_widget_with=i))

    suggestions = get_auto_ignore_suggestions(store, paths, "ads", "ad-current")

    assert len(suggestions) == 1
    s = suggestions[0]
    assert (s["x"], s["y"], s["width"], s["height"]) == WIDGET
    assert s["reason"] == "dynamic-content"
    assert s["frequency"] == 4
    assert s["variability"] >= 0.03


def test_the_same_change_every_run_is_not_suggested(workspace):
    """An unfixed regression repeats too, but renders identically each time.

    This is the case that made the previous implementation propose masking the
    defect it was supposed to surface.
    """
    paths, store = workspace
    frozen = _page(fill_widget_with=7)
    for i in range(4):
        _add_run(paths, store, f"bug-{i}", "bug", [WIDGET], frozen.copy())

    suggested, skipped = analyze_repeating_regions(store, paths, "bug", "bug-current")

    assert suggested == []
    assert [s["reason"] for s in skipped] == ["stable-content"]


def test_a_region_covering_the_page_is_not_suggested(workspace):
    """Whatever it is, it is not a widget."""
    paths, store = workspace
    whole_page = (0, 0, PAGE_W, PAGE_H - 10)
    for i in range(4):
        img = np.full((PAGE_H, PAGE_W, 3), 240, dtype=np.uint8)
        rng = np.random.default_rng(i)
        img[0:PAGE_H - 10, :] = rng.integers(0, 255, size=(PAGE_H - 10, PAGE_W, 3), dtype=np.uint8)
        _add_run(paths, store, f"big-{i}", "big", [whole_page], img)

    suggested, skipped = analyze_repeating_regions(store, paths, "big", "big-current")

    assert suggested == []
    assert [s["reason"] for s in skipped] == ["too-large"]


def test_runs_that_passed_count_against_a_region(workspace):
    """A region absent from recent captures is not "always changing".

    Passing runs record no regions, which is exactly the evidence that the area
    held still — so they belong in the denominator.
    """
    paths, store = workspace
    for i in range(2):
        _add_run(paths, store, f"mix-fail-{i}", "mix", [WIDGET], _page(fill_widget_with=i))
    for i in range(3):
        _add_run(paths, store, f"mix-pass-{i}", "mix", [], _page(fill_widget_with=None), status="PASS")

    suggested, skipped = analyze_repeating_regions(store, paths, "mix", "mix-current")

    assert suggested == []
    assert [s["reason"] for s in skipped] == ["appears-in-some-runs-only"]


def test_one_run_matching_the_baseline_does_not_disqualify_a_widget(workspace):
    """An ad slot serves the baseline's own creative every so often.

    That run comes back with no diff at all. Requiring a literal every-run
    streak would drop the suggestion on exactly the pages the feature exists
    for — measured at 3 of 4 on a real rotating ad.
    """
    paths, store = workspace
    for i in range(3):
        _add_run(paths, store, f"ad-{i}", "ads", [WIDGET], _page(fill_widget_with=i))
    _add_run(paths, store, "ad-same", "ads", [], _page(fill_widget_with=None), status="PASS")

    suggested, _ = analyze_repeating_regions(store, paths, "ads", "ad-current")

    assert len(suggested) == 1
    assert suggested[0]["frequency"] == 3
    assert suggested[0]["total_runs_analyzed"] == 4


def test_a_single_appearance_is_not_a_pattern(workspace):
    paths, store = workspace
    _add_run(paths, store, "once-0", "once", [WIDGET], _page(fill_widget_with=1))
    for i in range(3):
        _add_run(paths, store, f"once-clean-{i}", "once", [], _page(fill_widget_with=None), status="PASS")

    suggested, skipped = analyze_repeating_regions(store, paths, "once", "once-current")

    assert suggested == []
    assert skipped == []


def test_suggestions_do_not_creep_across_the_page(workspace):
    """One run merging the widget with a neighbouring change must not stretch
    the suggestion over the neighbour."""
    paths, store = workspace
    x, y, w, h = WIDGET
    merged = (x, y, w + 200, h)  # widget plus something next to it
    for i in range(3):
        _add_run(paths, store, f"creep-{i}", "creep", [WIDGET], _page(fill_widget_with=i))
    _add_run(paths, store, "creep-3", "creep", [merged], _page(fill_widget_with=9))

    suggested, _ = analyze_repeating_regions(store, paths, "creep", "creep-current")

    assert len(suggested) == 1
    assert suggested[0]["width"] == w
