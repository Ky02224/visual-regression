"""What the DOM knows about an image, and about which element is which.

Three findings from live measurement drove these, all in the same area — the
rule engine deciding whether an element is gone, moved, or broken:

* A failed image load is a fact the browser reports (`complete` with
  `naturalWidth === 0`), and nothing was reading it. The rule engine scored
  0/10 on broken-image; with the fact recorded it scores 10/10.
* Geometry matching gives up past 100px, so an image pushed down by a reflow
  looked removed and was reported as a broken image — 3 false alarms in 10
  layout-issue/missing-element trials. An image's decoded size fingerprints the
  file itself, so it finds the image wherever the reflow put it.
* Matching on tag and size alone pairs two different list items: delete one
  <li> and the next slides into its slot, so a removal reads as a move. Text
  separates them, and truncation (the one edit that legitimately rewrites an
  element's text) leaves one side a prefix of the other. Measured paired over
  52 live trials: missing-element 3->5, text-issue 5->7, nothing lower.
"""
from visual_regression.ai_features import diagnose_from_dom_diff
from visual_regression.models import DiffRegion

REGION = DiffRegion(x=0, y=0, width=800, height=600, area=480000, mean_delta=45.0)


def img(x=100, y=100, w=200, h=150, nw=800, nh=600, cmp=True, eid=None):
    e = {"tag": "img", "x": x, "y": y, "w": w, "h": h, "nw": nw, "nh": nh, "cmp": cmp}
    if eid:
        e["eid"] = eid
    return e


def li(y, txt, x=50, w=300, h=24):
    return {"tag": "li", "x": x, "y": y, "w": w, "h": h, "txt": txt}


class TestFailedImageLoad:
    def test_an_image_that_stops_decoding_is_a_broken_image(self):
        baseline = [img(eid="hero")]
        current = [img(nw=0, nh=0, eid="hero")]

        label, evidence = diagnose_from_dom_diff(baseline, current, REGION)

        assert label == "broken-image"
        assert "decoded to nothing" in evidence

    def test_an_image_still_loading_is_not_called_broken(self):
        """naturalWidth is legitimately 0 until the decode finishes; only
        `complete` distinguishes 'failed' from 'not yet'."""
        baseline = [img(eid="hero")]
        current = [img(nw=0, nh=0, cmp=False, eid="hero")]

        label, _ = diagnose_from_dom_diff(baseline, current, REGION)

        assert label != "broken-image"

    def test_an_image_that_was_never_decoded_in_the_baseline_proves_nothing(self):
        baseline = [img(nw=0, nh=0, eid="hero")]
        current = [img(nw=0, nh=0, eid="hero")]

        label, _ = diagnose_from_dom_diff(baseline, current, REGION)

        assert label != "broken-image"


class TestImageFingerprint:
    def test_an_image_pushed_out_of_matching_range_is_not_reported_missing(self):
        """The reflow case: same image, 300px lower, well past the 100px cap."""
        baseline = [img(y=100)]
        current = [img(y=400)]

        label, _ = diagnose_from_dom_diff(baseline, current, REGION)

        assert label != "broken-image", "the image is still on the page"

    def test_an_image_genuinely_removed_is_still_reported(self):
        """The guard must not swallow real removals — it only excuses an image
        whose decoded size is still present somewhere."""
        baseline = [img()]
        current = []

        label, _ = diagnose_from_dom_diff(baseline, current, REGION)

        assert label == "broken-image"

    def test_a_different_image_at_the_same_place_does_not_excuse_the_removal(self):
        baseline = [img(nw=800, nh=600)]
        current = [img(y=400, nw=123, nh=456)]

        label, _ = diagnose_from_dom_diff(baseline, current, REGION)

        assert label == "broken-image"


class TestTextIdentity:
    def test_a_deleted_list_item_is_not_its_neighbour_sliding_up(self):
        baseline = [li(100, "Introduction to widgets"), li(140, "Advanced widget theory")]
        current = [li(100, "Advanced widget theory")]

        label, _ = diagnose_from_dom_diff(baseline, current, REGION)

        assert label == "missing-element"

    def test_a_clipped_element_still_matches_its_own_element(self):
        """Truncation clips with CSS and leaves textContent alone, so the two
        sides read identically here — which is what lets the constraint stay
        strict without breaking the class it could most easily break."""
        baseline = [dict(li(100, "Introduction to widgets", w=300), sw=290, cw=300)]
        current = [dict(li(100, "Introduction to widgets", w=28), sw=290, cw=28)]

        label, _ = diagnose_from_dom_diff(baseline, current, REGION)

        assert label == "text-issue"

    def test_text_rewritten_to_something_unrelated_is_not_the_same_element(self):
        baseline = [li(100, "Introduction to widgets", w=300)]
        current = [li(100, "Quarterly earnings report", w=300)]

        label, _ = diagnose_from_dom_diff(baseline, current, REGION)

        assert label == "missing-element"

    def test_short_labels_are_left_to_geometry(self):
        """Nav items like 'Home'/'Docs' are too short to identify anything;
        requiring them to agree would break matching on every nav bar."""
        baseline = [li(100, "Home"), li(140, "Docs")]
        current = [li(140, "Home"), li(180, "Docs")]

        label, _ = diagnose_from_dom_diff(baseline, current, REGION)

        assert label == "layout-issue"


class TestRepeatedText:
    """Repeated text is ordinary — a link's label duplicated on its inner
    <span>, a desktop and mobile copy of the same nav. It used to defeat the
    identity tier ("ambiguous, fall through to geometry"), and geometry gives up
    past 100px, so an element a reflow had pushed 148px down came back unmatched
    and was reported as removed. That was 11 of 23 layout-issue trials on the
    corrected exam.

    What separates a move from a deletion is not position but count.
    """

    def test_a_moved_element_is_found_among_its_twins(self):
        baseline = [li(100, "To the user guide"), li(140, "To the user guide")]
        current = [li(100, "To the user guide"), li(288, "To the user guide")]

        label, _ = diagnose_from_dom_diff(baseline, current, REGION)

        assert label == "layout-issue"

    def test_losing_one_of_the_twins_is_still_a_removal(self):
        """The count is what makes the match safe: with a copy genuinely gone,
        pairing the survivor would hide the deletion."""
        baseline = [li(100, "To the user guide"), li(140, "To the user guide")]
        current = [li(100, "To the user guide")]

        label, _ = diagnose_from_dom_diff(baseline, current, REGION)

        assert label == "missing-element"

    def test_gaining_a_twin_does_not_hide_a_move(self):
        baseline = [li(100, "To the user guide")]
        current = [li(300, "To the user guide"), li(500, "To the user guide")]

        label, _ = diagnose_from_dom_diff(baseline, current, REGION)

        assert label == "layout-issue"


def svg(x=100, y=100, w=24, h=24):
    return {"tag": "svg", "x": x, "y": y, "w": w, "h": h}


class TestVectorIconsUnderReflow:
    """<svg>, <canvas> and <video> carry no decoded size, so the <img>
    fingerprint above cannot see them. Every icon a reflow pushed past the
    geometry cap was therefore reported as a broken image — four sites out of
    four in a layout-issue probe (preact, bootstrap, pydantic, linuxfoundation).

    Their rendered box stands in, decided by count and column: a reflow moves
    content down its own column and removes nothing.
    """

    def test_an_icon_pushed_down_the_page_is_not_a_broken_image(self):
        baseline = [svg(y=100)]
        current = [svg(y=460)]

        label, _ = diagnose_from_dom_diff(baseline, current, REGION)

        assert label != "broken-image"

    def test_an_icon_that_is_really_gone_is_still_reported(self):
        baseline = [svg()]
        current = []

        label, _ = diagnose_from_dom_diff(baseline, current, REGION)

        assert label == "broken-image"

    def test_losing_one_of_several_identical_icons_is_reported(self):
        """A nav bar of same-sized icons is the case count exists to handle."""
        baseline = [svg(y=100), svg(y=140), svg(y=180)]
        current = [svg(y=100), svg(y=140)]

        label, _ = diagnose_from_dom_diff(baseline, current, REGION)

        assert label == "broken-image"

    def test_an_unrelated_icon_in_another_column_does_not_excuse_it(self):
        """Count alone would pass this; a reflow does not move things sideways."""
        baseline = [svg(x=100, y=100)]
        current = [svg(x=900, y=900)]

        label, _ = diagnose_from_dom_diff(baseline, current, REGION)

        assert label == "broken-image"
