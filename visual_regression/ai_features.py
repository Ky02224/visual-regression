from __future__ import annotations

import logging
import re
from typing import Dict, Iterable, Sequence

import cv2
import numpy as np

from .models import CompareResult

logger = logging.getLogger(__name__)


RULE_FEATURE_NAMES = [
    "mismatch_pct",
    "ssim_score",
    "region_count",
    "largest_region_ratio",
    "mean_region_ratio",
    "mean_delta",
    "max_delta",
    "width_ratio",
    "height_ratio",
]

# Kept for backward compatibility with older metadata/tests.
FEATURE_NAMES = RULE_FEATURE_NAMES

# DOM feature names for multimodal fusion (Proposal F)
# These are derived from dom_snapshot.json saved by browser.py during capture
DOM_FEATURE_NAMES = [
    # Tag count features (normalized by total_elements)
    "dom_div_ratio", "dom_span_ratio", "dom_p_ratio", "dom_a_ratio",
    "dom_button_ratio", "dom_input_ratio", "dom_select_ratio", "dom_textarea_ratio",
    "dom_img_ratio", "dom_video_ratio", "dom_iframe_ratio", "dom_form_ratio",
    "dom_nav_ratio", "dom_header_ratio", "dom_footer_ratio", "dom_main_ratio",
    "dom_section_ratio", "dom_article_ratio", "dom_h1_ratio", "dom_h2_ratio",
    "dom_h3_ratio", "dom_table_ratio", "dom_ul_ratio", "dom_ol_ratio",
    # Structural features
    "dom_total_elements_log",  # log1p(total_elements) to normalize
    "dom_avg_depth",
    "dom_interactive_ratio",
    # Boolean flags
    "dom_has_form", "dom_has_img", "dom_has_video", "dom_has_iframe",
    # DIFF features (baseline vs current delta)
    "dom_total_elements_diff",  # (current - baseline) / max(baseline, 1)
    "dom_interactive_diff",
    "dom_div_diff", "dom_img_diff", "dom_button_diff",
    "dom_nav_diff", "dom_form_diff", "dom_h1_diff",
]

# Element-level structural features. DOM_FEATURE_NAMES above are page-level
# aggregates — how many divs, how much the element count moved — and on a page
# with two thousand elements, one of them disappearing shifts the total by
# 0.05%, which is indistinguishable from noise. That is the measured gap: with
# these aggregates the model scores 22.2% on real pages while
# diagnose_from_dom_diff, which matches individual elements between the two
# snapshots, scores 94.2% on the same inputs. The difference is not reasoning
# ability but evidence precision, so these features hand the model the same
# element-level comparison the rule engine performs.
STRUCT_FEATURE_NAMES = [
    "struct_matched_ratio",
    "struct_unmatched_ratio",
    "struct_unmatched_strong_ratio",   # vanished WITH an id or distinctive text
    "struct_unmatched_media_ratio",
    "struct_unmatched_text_ratio",
    "struct_unmatched_max_area",       # largest vanished element, as page fraction
    "struct_unmatched_total_area",
    "struct_added_ratio",              # present now, absent from the baseline
    "struct_moved_ratio",
    "struct_moved_max_disp",           # normalised by page height
    "struct_moved_mean_disp",
    "struct_resized_ratio",
    "struct_font_changed_ratio",
    "struct_color_changed_ratio",
]

# FEATURE_NAMES now includes both rule and DOM features for the extended model
FULL_FEATURE_NAMES = RULE_FEATURE_NAMES + DOM_FEATURE_NAMES + STRUCT_FEATURE_NAMES

# Matching is quadratic in element count, and training runs it over thousands of
# pairs. Ranking by area first keeps the cost bounded and drops what a screenshot
# comparison would not have shown anyway — a 4px spacer vanishing is not the
# defect anyone is looking for.
_STRUCT_MAX_ELEMENTS = 300


def _dom_snapshot_to_raw(snapshot: dict) -> dict:
    """Convert a raw DOM snapshot dict (from JS) to a normalized feature dict."""
    import math
    tag_counts = snapshot.get("tag_counts", {})
    raw_count = int(snapshot.get("total_elements", 0))
    total = max(raw_count, 1)  # safe divisor only
    interactive = int(snapshot.get("interactive_count", 0))
    return {
        "total_elements": raw_count,  # raw (not clamped) for diff features
        "avg_depth": float(snapshot.get("avg_depth", 0.0)),
        "interactive_count": interactive,
        "interactive_ratio": interactive / total,
        "total_elements_log": math.log1p(raw_count),  # log1p(0)=0 for empty snapshots
        "has_form": float(bool(snapshot.get("has_form", False))),
        "has_img": float(bool(snapshot.get("has_img", False))),
        "has_video": float(bool(snapshot.get("has_video", False))),
        "has_iframe": float(bool(snapshot.get("has_iframe", False))),
        **{tag: int(tag_counts.get(tag, 0)) / total for tag in [
            "div", "span", "p", "a", "button", "input", "select", "textarea",
            "img", "video", "iframe", "form", "nav", "header", "footer", "main",
            "section", "article", "h1", "h2", "h3", "table", "ul", "ol",
        ]},
    }


_ZERO_DOM_SNAPSHOT = {"tag_counts": {}, "total_elements": 0, "avg_depth": 0.0,
                      "interactive_count": 0, "has_form": False, "has_img": False,
                      "has_video": False, "has_iframe": False}


def dom_feature_vector_from_snapshots(
    baseline_snapshot: "dict | None",
    current_snapshot: "dict | None",
) -> np.ndarray:
    """Extract a fixed-size DOM feature vector from baseline+current DOM snapshots.

    If either snapshot is None/missing, returns a zero vector (graceful fallback).
    Features include per-snapshot ratios AND delta (current - baseline) features.
    """
    b = _dom_snapshot_to_raw(baseline_snapshot or _ZERO_DOM_SNAPSHOT)
    c = _dom_snapshot_to_raw(current_snapshot or _ZERO_DOM_SNAPSHOT)

    # Use baseline snapshot for absolute features (stable reference)
    feats = [
        # Tag ratios from baseline (24 features)
        b["div"], b["span"], b["p"], b["a"],
        b["button"], b["input"], b["select"], b["textarea"],
        b["img"], b["video"], b["iframe"], b["form"],
        b["nav"], b["header"], b["footer"], b["main"],
        b["section"], b["article"], b["h1"], b["h2"],
        b["h3"], b["table"], b["ul"], b["ol"],
        # Structural features from baseline (3 features)
        b["total_elements_log"],
        b["avg_depth"],
        b["interactive_ratio"],
        # Boolean flags from baseline (4 features)
        b["has_form"], b["has_img"], b["has_video"], b["has_iframe"],
        # DIFF features: (current - baseline) / max(baseline_total, 1) (7 features)
        (c["total_elements"] - b["total_elements"]) / max(b["total_elements"], 1),
        (c["interactive_count"] - b["interactive_count"]) / max(b["total_elements"], 1),
        c["div"] - b["div"],
        c["img"] - b["img"],
        c["button"] - b["button"],
        c["nav"] - b["nav"],
        c["form"] - b["form"],
        c["h1"] - b["h1"],
    ]
    return np.asarray(feats, dtype=np.float32)


def load_dom_snapshot(image_path: "object | None") -> "dict | None":
    """Load the DOM snapshot sidecar JSON for an image path. Returns None if missing."""
    if image_path is None:
        return None
    try:
        from pathlib import Path
        import json as _json
        dom_path = Path(str(image_path)).with_suffix('.dom.json')
        if dom_path.exists():
            return _json.loads(dom_path.read_text(encoding='utf-8'))
    except Exception as exc:
        logger.debug("Failed to load DOM snapshot for %s: %s", image_path, exc)
    return None


def extract_dom_html_diff(baseline_dom: dict | None, current_dom: dict | None, region: object | None) -> dict[str, str]:
    """Extract code-level HTML element diff between baseline and current snapshots within diff region."""
    if not region:
        return {"baseline_html": "", "current_html": ""}
    rx1, ry1 = getattr(region, "x", 0), getattr(region, "y", 0)
    rx2, ry2 = rx1 + getattr(region, "width", 0), ry1 + getattr(region, "height", 0)
    
    def _find_html_snippet(dom_snapshot):
        if not dom_snapshot or "elements" not in dom_snapshot:
            return ""
        matched = []
        for el in dom_snapshot.get("elements", []):
            ex1, ey1 = el.get("x", 0), el.get("y", 0)
            ex2, ey2 = ex1 + el.get("w", 0), ey1 + el.get("h", 0)
            if max(rx1, ex1) < min(rx2, ex2) and max(ry1, ey1) < min(ry2, ey2):
                tag = el.get("tag", "div").lower()
                text = el.get("text", "").strip()
                cls = el.get("class", "").strip()
                cls_attr = f' class="{cls}"' if cls else ''
                matched.append(f'<{tag}{cls_attr}>{text}</{tag}>')
        return " ".join(matched[:3])
        
    b_html = _find_html_snippet(baseline_dom)
    c_html = _find_html_snippet(current_dom)
    return {"baseline_html": b_html, "current_html": c_html}

def _elements_near_region(elements: list, region: object, margin: int = 40) -> list:
    """Elements whose bounding box overlaps the region (expanded by margin)."""
    if not elements or region is None:
        return []
    rx1 = getattr(region, "x", 0) - margin
    ry1 = getattr(region, "y", 0) - margin
    rx2 = rx1 + getattr(region, "width", 0) + 2 * margin
    ry2 = ry1 + getattr(region, "height", 0) + 2 * margin
    found = []
    for el in elements:
        ex1, ey1 = el.get("x", 0), el.get("y", 0)
        ex2, ey2 = ex1 + el.get("w", 0), ey1 + el.get("h", 0)
        if max(rx1, ex1) < min(rx2, ex2) and max(ry1, ey1) < min(ry2, ey2):
            found.append(el)
    return found


def _match_element(el: dict, candidates: list, max_dist: float = 100.0, claimed: set | None = None) -> dict | None:
    """Find the element in `candidates` that corresponds to `el`, or None.

    `claimed` (by `id()` of the candidate dict) excludes candidates already
    matched to a *different* baseline element earlier in the same diff —
    without this, two different baseline elements can each independently
    pick the same surviving current element as their "nearest" match (e.g.
    a removed element and its former neighbor both treat one remaining
    element as their own best match). That silently erases the removal:
    the removed element never reaches the "missing" bucket because it looks
    matched. Callers doing a multi-element diff should thread one growing
    `claimed` set through all calls so each current element can only be
    claimed once.

    Prefers a stable identity match via `id` over guessing from geometry: a
    page's own id attribute is the actual identity of a DOM node, unaffected
    by reflow, whereas position/size are just where that node happened to
    render this time. ids are supposed to be unique per page, so an id match
    is trusted regardless of distance.

    Falling back further, exact text content is the next-strongest identity
    signal — stronger than position for exactly the case that breaks
    position-based matching: a repeating list (story links, nav items)
    where removing one item reflows every item after it. None of this
    module's mutations change an element's text (color/font/position/
    truncation edits all leave textContent alone), so on a page with no
    ids at all, "same tag + identical text" still reliably survives a
    sibling being removed elsewhere, whereas "same tag + nearby position"
    does not. Requires a minimum length and uniqueness among candidates so
    short/duplicated boilerplate text ("More", "Login") can't false-match.
    When the text is specific enough but genuinely absent from every
    candidate, that absence is trusted as "removed" and returned as a firm
    None rather than falling through to geometry — otherwise the geometry
    fallback below would happily match it to whichever unrelated same-tag
    neighbor reflowed into that position, recreating the exact false
    "moved" verdict this tier exists to prevent.

    A shared `class` string is a weaker signal — real sites commonly reuse
    one class across many unrelated instances of a repeated pattern (every
    story-title link, every thumbnail), so two elements matching on class
    doesn't mean they're the same node. It's only used as a tie-breaker
    within the geometry-filtered candidate pool below, not as a standalone
    identity check, so a same-class element clear across the page can't
    hijack the match.

    Falls back to nearest same-tag, similarly-sized element when none of
    the above apply (many elements — especially generic <span>/<p> — have
    no id and short/duplicated text). max_dist is generous (100px) because
    this tier now only runs after id/text identity has already failed to
    resolve the element, so it's mainly catching short-text siblings (e.g.
    a "(example.com)" source tag next to a headline) that get pushed a
    real distance by an unrelated edit elsewhere on the same line —
    rejecting them as "moved too far" just recreates a false "missing"
    verdict for an element that's still plainly present. Proximity alone is
    not enough on its own, though: on text-dense pages a removed element's
    empty space can still get a same-tag neighbor within max_dist purely by
    reflow coincidence.
    Requiring width/height to stay within a band rejects those false
    matches (e.g. a 453px-wide nav span "matching" an unrelated 65px-wide
    story span that happened to land nearby). Width gets a looser band than
    height: a width-only overflow/truncation (text clipped via `overflow:
    hidden`) is a legitimate same-element edit that shouldn't be treated as
    a non-match, whereas height changing along with width is a stronger
    signal of a genuinely different element.
    """
    if claimed:
        candidates = [c for c in candidates if id(c) not in claimed]
    status, match = _match_by_identity(el, candidates)
    if status != "none":
        return match
    match, _dist = _match_by_geometry(el, candidates, max_dist)
    return match


def _has_struct_identity(el: dict) -> bool:
    """Whether a vanished element can be trusted as genuinely gone.

    An id, or text long enough to be specific, makes "not found anywhere in the
    current page" an exact global check. Without either, absence is a proximity
    guess that reflow alone can fake — the same distinction diagnose_from_dom_diff
    draws between its strong and weak missing buckets.
    """
    if el.get("eid"):
        return True
    return len(str(el.get("txt") or "").strip()) >= 12


def struct_feature_vector(baseline_elements: list | None,
                          current_elements: list | None) -> np.ndarray:
    """Element-level comparison of two DOM snapshots, as a fixed-size vector.

    Answers, per element rather than per page: did this one vanish, did it move,
    did its font or colour change. Aggregate counts cannot express that — one
    element leaving a 2000-element page moves every aggregate by 0.05% — which is
    why the model scores 22.2% on evidence the rule engine turns into 94.2%.

    Zero vector when either snapshot is missing, so callers without DOM sidecars
    (the SDK upload path) degrade to the previous behaviour instead of failing.
    """
    names = STRUCT_FEATURE_NAMES
    if not baseline_elements or not current_elements:
        return np.zeros(len(names), dtype=np.float32)

    def _area(e: dict) -> float:
        return float(e.get("w", 0) or 0) * float(e.get("h", 0) or 0)

    baseline = sorted(baseline_elements, key=_area, reverse=True)[:_STRUCT_MAX_ELEMENTS]
    current = sorted(current_elements, key=_area, reverse=True)[:_STRUCT_MAX_ELEMENTS]
    if not baseline:
        return np.zeros(len(names), dtype=np.float32)

    page_w = max((float(e.get("x", 0)) + float(e.get("w", 0)) for e in baseline), default=1.0) or 1.0
    page_h = max((float(e.get("y", 0)) + float(e.get("h", 0)) for e in baseline), default=1.0) or 1.0
    page_area = max(page_w * page_h, 1.0)

    # Identity first, then geometry in ascending distance — the same two-phase
    # resolution diagnose_from_dom_diff uses, so a confident pairing cannot be
    # scooped by a same-tag sibling that merely came first in document order.
    claimed: set = set()
    resolved: dict[int, dict | None] = {}
    pending: list[dict] = []
    for el in baseline:
        available = [c for c in current if id(c) not in claimed]
        status, match = _match_by_identity(el, available)
        if status == "found":
            resolved[id(el)] = match
            claimed.add(id(match))
        elif status == "absent":
            resolved[id(el)] = None
        else:
            pending.append(el)

    scored = []
    for el in pending:
        available = [c for c in current if id(c) not in claimed]
        match, dist = _match_by_geometry(el, available, max_dist=100.0)
        scored.append((dist if match is not None else float("inf"), el, match))
    scored.sort(key=lambda t: t[0])
    for _dist, el, match in scored:
        if match is not None and id(match) in claimed:
            match = None
        resolved[id(el)] = match
        if match is not None:
            claimed.add(id(match))

    total = float(len(baseline))
    matched = unmatched = unmatched_strong = unmatched_media = unmatched_text = 0
    unmatched_max_area = unmatched_total_area = 0.0
    moved = resized = font_changed = color_changed = 0
    displacements: list[float] = []

    for el in baseline:
        match = resolved.get(id(el))
        if match is None:
            unmatched += 1
            tag = str(el.get("tag") or "")
            if _has_struct_identity(el):
                unmatched_strong += 1
            if tag in _MEDIA_TAGS:
                unmatched_media += 1
            if tag in _TEXT_TAGS:
                unmatched_text += 1
            area = _area(el)
            unmatched_total_area += area
            unmatched_max_area = max(unmatched_max_area, area)
            continue

        matched += 1
        dx = abs(float(match.get("x", 0)) - float(el.get("x", 0)))
        dy = abs(float(match.get("y", 0)) - float(el.get("y", 0)))
        disp = (dx * dx + dy * dy) ** 0.5
        if dx > 30 or dy > 30:
            moved += 1
            displacements.append(disp)
        bw = max(float(el.get("w", 0) or 0), 1.0)
        bh = max(float(el.get("h", 0) or 0), 1.0)
        if (abs(float(match.get("w", 0)) - float(el.get("w", 0))) / bw > 0.25
                or abs(float(match.get("h", 0)) - float(el.get("h", 0))) / bh > 0.25):
            resized += 1
        if el.get("font") and match.get("font") and el["font"] != match["font"]:
            font_changed += 1
        if el.get("color") and match.get("color") and el["color"] != match["color"]:
            color_changed += 1

    added = sum(1 for c in current if id(c) not in claimed)

    feats = [
        matched / total,
        unmatched / total,
        unmatched_strong / total,
        unmatched_media / total,
        unmatched_text / total,
        min(unmatched_max_area / page_area, 1.0),
        min(unmatched_total_area / page_area, 1.0),
        added / max(float(len(current)), 1.0),
        moved / total,
        min(max(displacements, default=0.0) / page_h, 1.0),
        min((sum(displacements) / len(displacements) if displacements else 0.0) / page_h, 1.0),
        resized / total,
        font_changed / total,
        color_changed / total,
    ]
    assert len(feats) == len(names), "struct feature count drifted from its names"
    return np.array(feats, dtype=np.float32)


def _match_by_identity(el: dict, candidates: list) -> tuple[str, dict | None]:
    """id/text identity tiers of _match_element, split out so the caller can
    resolve every element's identity match first (order-independent — ids
    and unique-in-page text are unambiguous regardless of which baseline
    element is processed first) before falling back to geometry only for
    what's left. See _match_element's docstring for the reasoning behind
    each tier.

    Returns ("found", match) | ("absent", None) — specific text confirmed
    nowhere in candidates, caller must not fall through to geometry |
    ("none", None) — no identity signal available, try geometry.
    """
    tag = el.get("tag")
    eid = el.get("eid")
    if eid:
        for c in candidates:
            if c.get("tag") == tag and c.get("eid") == eid:
                return "found", c

    etxt = el.get("txt")
    if etxt and len(etxt) >= 8:
        txt_matches = [c for c in candidates if c.get("tag") == tag and c.get("txt") == etxt]
        if len(txt_matches) == 1:
            return "found", txt_matches[0]
        if not txt_matches:
            return "absent", None
        # Multiple candidates share this exact text — ambiguous, fall
        # through to geometry rather than guess among identical text.

    return "none", None


def _match_by_geometry(el: dict, candidates: list, max_dist: float = 100.0) -> tuple[dict | None, float]:
    """Geometry-fallback tier of _match_element: nearest same-tag,
    similarly-sized element. Returns (match_or_None, distance) — the
    distance lets the caller resolve *all* elements needing this fallback
    tier in order of match confidence (closest first) instead of DOM
    order, so a confident pairing can't get scooped by a same-tag sibling
    that merely happened to be processed first (see the two-phase loop in
    diagnose_from_dom_diff).
    """
    tag = el.get("tag")
    ecls = el.get("ecls")
    ew, eh = max(el.get("w", 0), 1), max(el.get("h", 0), 1)
    # Distance uses the top-left corner, not the box center. For same-size
    # candidates the two are identical up to a constant offset (w/2, h/2 is
    # the same on both sides), so this changes nothing for the ordinary
    # "did it move" comparison. It matters specifically when a candidate's
    # width shrank (a text-truncation edit, left-anchored so the left edge
    # doesn't move): the center drifts left by half the lost width even
    # though the element never actually moved, artificially inflating its
    # distance past an unrelated same-size sibling sitting one row away —
    # confirmed on a real page where a truncated element's own unmoved
    # position scored 91px (center-based) against itself, while a same-
    # size sibling merely 20px further down scored closer and stole the
    # match, silently discarding the truncation this element should have
    # been diagnosed with.
    ex, ey = el.get("x", 0), el.get("y", 0)
    best, best_dist = None, max_dist
    best_cls, best_cls_dist = None, max_dist
    for c in candidates:
        if c.get("tag") != tag:
            continue
        cw, ch = max(c.get("w", 0), 1), max(c.get("h", 0), 1)
        # Text tags get a much lower width floor than the generic 0.25x: a
        # fixed-width `overflow: hidden` clip (the text-issue signal itself)
        # can shrink an element to a small fraction of its baseline width
        # regardless of how wide it started — that's a legitimate same-
        # element edit, not evidence this is a different node. Height stays
        # the tighter band either way, since it's unaffected by truncation
        # and remains the stronger "same box" signal. Non-text tags (img,
        # div, etc.) keep the original floor: a drastic width shrink there
        # is more likely a genuinely different element.
        width_floor = 0.03 if tag in _TEXT_TAGS else 0.25
        if not (width_floor <= cw / ew <= 4.0 and 0.4 <= ch / eh <= 2.5):
            continue
        ccx, ccy = c.get("x", 0), c.get("y", 0)
        dist = ((ex - ccx) ** 2 + (ey - ccy) ** 2) ** 0.5
        if dist < best_dist:
            best, best_dist = c, dist
        if ecls and c.get("ecls") == ecls and dist < best_cls_dist:
            best_cls, best_cls_dist = c, dist
    # Among candidates that already pass the geometry band, prefer the one
    # that also shares a class — it's more likely the same node than a
    # same-tag/same-size stranger that happens to be marginally closer.
    if best_cls is not None:
        return best_cls, best_cls_dist
    return best, best_dist


_MEDIA_TAGS = {"img", "video", "svg", "canvas"}
_TEXT_TAGS = {"p", "span", "a", "button", "h1", "h2", "h3", "h4", "h5", "h6", "label", "code", "pre", "li"}

_CSS_RGB_RE = re.compile(r"rgba?\(\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\s*\)")


def _parse_css_color(value: str | None) -> tuple | None:
    """Parse a getComputedStyle() color string to (r, g, b), or None if missing/transparent."""
    if not value:
        return None
    m = _CSS_RGB_RE.match(value.strip())
    if not m:
        return None
    r, g, b = float(m.group(1)), float(m.group(2)), float(m.group(3))
    alpha = float(m.group(4)) if m.group(4) is not None else 1.0
    if alpha <= 0.02:
        return None
    return (r, g, b)


def _color_distance(a: tuple, b: tuple) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _relative_luminance(rgb: tuple) -> float:
    """WCAG-style relative luminance from an (r, g, b) 0-255 tuple."""
    def _lin(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast_ratio(a: tuple, b: tuple) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def diagnose_from_dom_diff(
    baseline_elements: list,
    current_elements: list,
    region: object,
    allow_missing: bool = True,
) -> tuple[str | None, str]:
    """Deterministically diagnose a defect type from real baseline-vs-current DOM structure.

    Unlike the trained CNN, this compares actual element geometry/tags/fonts captured
    from the two page loads, so it does not need to have "seen" a given site before —
    it generalizes to any website by construction. Returns (label, evidence) or
    (None, "") when the structural evidence is not conclusive.

    Removing or restyling one element often has knock-on effects: a removed
    image reflows everything below it, and a font swap changes an element's
    own rendered width/height as a side effect. Scanning elements in document
    order and returning on the first verdict picked up whichever side effect
    happened to come first, not the root cause. Instead, every baseline
    element is classified into a bucket, then buckets are resolved in
    priority order: id/text-backed missing > text-issue > font > color >
    moved > identity-less missing. A "missing" verdict backed by a stable
    id or long text is trusted up front — it's a real, exact signal. But a
    "missing" verdict backed by nothing except "no similar element found
    nearby" is the noisiest thing this function can report: almost any edit
    anywhere on the page causes some unrelated element to reflow past the
    geometry-match threshold, and unlike font/color/moved, "missing" isn't
    self-correcting if it's wrong about which element actually changed. So
    identity-less missing is checked last, as a fallback, rather than
    up front — otherwise it routinely drowns out the real color/font/
    text-issue signal on the element that actually changed. text-issue
    covers two DOM-observable readability

    `allow_missing=False` restricts the "element vanished" check to only
    fire when the vanished element had a strong standalone identity (an id,
    or specific/long-enough text) — never when it was only "nothing similar
    found nearby". Set this when `region` is a full-page fallback rather
    than a real pixel-diff region (see _dom_diff_region): with no pixel
    evidence to localize the search, a proximity-only "missing" is the
    noisiest possible verdict — a page's own dynamic content (rotating
    promo, lazy-loaded image, live counter) can look like a vanished
    element purely from page-to-page variance having nothing to do with the
    run under test. An id/text match, by contrast, is a global, exact check
    ("is this specific content anywhere on the page at all") rather than a
    local, fuzzy one, so it stays trustworthy even without a pixel region to
    scope the search.

    text-issue covers two DOM-observable readability defects: new text
    overflow/clipping (scrollWidth > clientWidth) and a foreground/
    background contrast collapse (WCAG-style ratio dropping from readable
    to unreadable).
    """
    baseline_near = _elements_near_region(baseline_elements, region)
    current_near = _elements_near_region(current_elements, region)
    if not baseline_near and not current_near:
        return None, ""

    # Match candidates are the *whole* current page, not just current_near:
    # id/text identity is supposed to be a global check (see _match_element's
    # docstring) — a real element that reflowed 60+px because of an edit
    # elsewhere on the page can easily land outside this region's narrow
    # margin, and scoping candidates to the region would make that global
    # check silently degrade into a local one, misreporting a still-present,
    # merely-shifted element as "missing". The geometry fallback tier inside
    # _match_element is unaffected either way since it's already bounded by
    # max_dist regardless of how large the candidate pool is.
    match_candidates = current_elements

    missing_media_strong, missing_generic_strong, missing_generic_weak = [], [], []
    moved, font_changed, color_changed, text_issue = [], [], [], []

    # Two-phase matching: identity (id/unique text) first, since those are
    # exact and order-independent — resolving them regardless of processing
    # order can't create a wrong pairing. Only the geometry-fallback tier
    # (no id, no unique-enough text — the common case for generic <span>/
    # <li> siblings in a list or nav bar) is ambiguous, and resolving those
    # in DOM order let a same-tag/same-size sibling that merely happened to
    # be processed first "steal" another element's rightful match (confirmed
    # on a real page: a moved nav link with a 5-char label got its match
    # taken by an unrelated, unmoved sibling that iterated first, so the
    # real move was silently missed). Deferring the fallback tier and
    # resolving it in ascending distance order — most confident pairing
    # claims first — fixes that without touching the already-unambiguous
    # identity tier or the geometry heuristics themselves.
    claimed_matches: set = set()
    resolved: dict[int, dict | None] = {}
    pending: list[dict] = []
    for el in baseline_near:
        available = [c for c in match_candidates if id(c) not in claimed_matches]
        status, match = _match_by_identity(el, available)
        if status == "found":
            resolved[id(el)] = match
            claimed_matches.add(id(match))
        elif status == "absent":
            resolved[id(el)] = None
        else:
            pending.append(el)

    scored = []
    for el in pending:
        available = [c for c in match_candidates if id(c) not in claimed_matches]
        match, dist = _match_by_geometry(el, available, max_dist=100.0)
        scored.append((dist if match is not None else float("inf"), el, match))
    scored.sort(key=lambda t: t[0])
    for _dist, el, match in scored:
        if match is not None and id(match) in claimed_matches:
            # Best candidate was claimed by a more confident (smaller-
            # distance) pairing resolved earlier in this sorted pass —
            # recompute against what's left rather than treating this
            # element as unmatched.
            available = [c for c in match_candidates if id(c) not in claimed_matches]
            match, _dist = _match_by_geometry(el, available, max_dist=100.0)
        if match is not None:
            claimed_matches.add(id(match))
        resolved[id(el)] = match

    for el in baseline_near:
        match = resolved[id(el)]
        tag = el.get("tag", "")
        if match is None:
            has_identity = bool(el.get("eid") or len(el.get("txt") or "") >= 8)
            if not allow_missing and not has_identity:
                # Only a fuzzy "nothing similar nearby" guess — exactly the
                # case that's unreliable without a real pixel region to
                # scope the search. Skip it rather than let page noise
                # masquerade as a defect.
                continue
            if tag in _MEDIA_TAGS:
                # Media elements never carry captured text (only _TEXT_TAGS
                # do), so requiring id/text identity here would make almost
                # every real image removal count as "weak" by construction —
                # exactly backwards, since img/video/svg/canvas are rare
                # enough per page that "nothing of this tag found nearby,
                # searched globally" is trustworthy on its own, unlike the
                # common tags below where that same check is routinely
                # fooled by reflow coincidence.
                missing_media_strong.append(el)
            elif has_identity:
                missing_generic_strong.append(el)
            else:
                # A "nothing similar nearby" guess with no id/text backing
                # it is the noisiest verdict this function can produce —
                # almost any edit on the page causes some unrelated element
                # to drift past the geometry-match threshold as a reflow
                # side effect. Queued as a last-resort fallback below rather
                # than dropped outright, since it's still the right call
                # when nothing else on the page actually changed.
                missing_generic_weak.append(el)
            continue
        # Truncation: scrollWidth > clientWidth means the text overflows its
        # box. Newly-overflowing (wasn't in baseline) is an unambiguous,
        # cheap-to-check signal — no ambiguity about root cause, so it's
        # checked first among the "matched but changed" cases.
        #
        # The 1.4x floor (not 1.1x) is deliberate: a webfont that finishes
        # loading between the baseline and current capture shifts an
        # untouched element's scrollWidth by font-metric noise alone — e.g.
        # a real capture pair confirmed 103px -> 119px (1.155x) on an
        # element whose position/size never changed, unrelated to the
        # actual edit elsewhere on the page. Real truncation defects (text
        # genuinely clipped by a narrowed container) measured 2.29x-3.25x
        # in the same eval — a wide, safe margin above the noise band, so
        # 1.4x filters the font-settling false positive without weakening
        # detection of genuine truncation.
        b_sw, b_cw = el.get("sw"), el.get("cw")
        c_sw, c_cw = match.get("sw"), match.get("cw")
        if tag in _TEXT_TAGS and b_sw is not None and b_cw and c_sw is not None and c_cw:
            baseline_overflowed = b_sw > b_cw * 1.4
            current_overflows = c_sw > c_cw * 1.4
            if current_overflows and not baseline_overflowed:
                text_issue.append((el, match, "text now overflows/clips its container"))
                continue
        # Check style properties (font/color) before geometry: a font swap
        # routinely changes the element's rendered width/height as a side
        # effect (e.g. a monospace fallback is wider per character), so
        # checking position/size drift first would misattribute the root
        # cause to "layout-issue" instead of the actual font/color edit.
        if tag in _TEXT_TAGS and el.get("font") and match.get("font") and el.get("font") != match.get("font"):
            font_changed.append((el, match))
            continue
        style_changed = False
        if tag in _TEXT_TAGS:
            for prop, human in (("color", "text color"), ("bg", "background color")):
                b_color = _parse_css_color(el.get(prop))
                c_color = _parse_css_color(match.get(prop))
                if b_color and c_color and _color_distance(b_color, c_color) > 30:
                    # A color edit that specifically wrecks readability
                    # (foreground/background contrast collapses) is a
                    # readability defect, not a cosmetic recolor.
                    b_fg, b_bg = _parse_css_color(el.get("color")), _parse_css_color(el.get("bg"))
                    c_fg, c_bg = _parse_css_color(match.get("color")), _parse_css_color(match.get("bg"))
                    if b_fg and b_bg and c_fg and c_bg:
                        b_ratio = _contrast_ratio(b_fg, b_bg)
                        c_ratio = _contrast_ratio(c_fg, c_bg)
                        if b_ratio >= 4.5 and c_ratio < 3.0:
                            text_issue.append((el, match, f"text contrast dropped from {b_ratio:.1f}:1 to {c_ratio:.1f}:1"))
                            style_changed = True
                            break
                    color_changed.append((el, match, prop, human))
                    style_changed = True
                    break
        if style_changed:
            continue
        bw, bh = max(el.get("w", 0), 1), max(el.get("h", 0), 1)
        dw = abs(match.get("w", 0) - el.get("w", 0)) / bw
        dh = abs(match.get("h", 0) - el.get("h", 0)) / bh
        dx = abs(match.get("x", 0) - el.get("x", 0))
        dy = abs(match.get("y", 0) - el.get("y", 0))
        if dw > 0.25 or dh > 0.25 or dx > 30 or dy > 30:
            moved.append((el, match))
            continue

    if missing_media_strong:
        tag = missing_media_strong[0].get("tag", "")
        return "broken-image", (
            f"DOM diff: a <{tag}> element present in the baseline page has no "
            f"matching element in the current page at the same position."
        )
    if missing_generic_strong:
        tag = missing_generic_strong[0].get("tag", "")
        return "missing-element", (
            f"DOM diff: a <{tag}> element present in the baseline page is missing "
            f"from the current page."
        )
    if text_issue:
        el, match, reason = text_issue[0]
        tag = el.get("tag", "")
        return "text-issue", f"DOM diff: the <{tag}> element's {reason}."
    if font_changed:
        el, match = font_changed[0]
        tag = el.get("tag", "")
        return "font-change", (
            f"DOM diff: the <{tag}> element's font changed from '{el.get('font')}' "
            f"to '{match.get('font')}'."
        )
    if color_changed:
        el, match, prop, human = color_changed[0]
        tag = el.get("tag", "")
        return "color-regression", (
            f"DOM diff: the <{tag}> element's {human} changed from "
            f"'{el.get(prop)}' to '{match.get(prop)}'."
        )
    if moved:
        el, match = moved[0]
        tag = el.get("tag", "")
        return "layout-issue", (
            f"DOM diff: the <{tag}> element's position/size shifted from "
            f"({el.get('x')},{el.get('y')},{el.get('w')}x{el.get('h')}) to "
            f"({match.get('x')},{match.get('y')},{match.get('w')}x{match.get('h')})."
        )
    # Weak (identity-less) generic "missing" verdicts are checked last, as
    # a fallback, rather than up front — see the loop above for why. Media
    # tags have no weak tier (see the loop above), so there's nothing to
    # check here for them.
    if missing_generic_weak:
        tag = missing_generic_weak[0].get("tag", "")
        return "missing-element", (
            f"DOM diff: a <{tag}> element present in the baseline page is missing "
            f"from the current page."
        )

    return None, ""


IMAGENET_MEAN = np.asarray([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.asarray([0.229, 0.224, 0.225], dtype=np.float32)
DEFAULT_IMAGE_SIZE = 224


def extract_rule_feature_dict(result: CompareResult) -> Dict[str, float]:
    total_pixels = float(max(result.total_pixels, 1))
    baseline_w, baseline_h = (result.baseline_size + [1, 1])[:2]
    current_w, current_h = (result.current_size + [1, 1])[:2]
    region_count = float(len(result.regions))
    if result.regions:
        region_areas = [float(region.area) for region in result.regions]
        region_deltas = [float(region.mean_delta) for region in result.regions]
        largest_region_ratio = max(region_areas) / total_pixels
        mean_region_ratio = float(np.mean(region_areas)) / total_pixels
        mean_delta = float(np.mean(region_deltas))
        max_delta = float(np.max(region_deltas))
    else:
        largest_region_ratio = 0.0
        mean_region_ratio = 0.0
        mean_delta = 0.0
        max_delta = 0.0

    return {
        "mismatch_pct": float(result.mismatch_pct),
        "ssim_score": float(result.ssim_score if result.ssim_score is not None else 1.0),
        "region_count": region_count,
        "largest_region_ratio": largest_region_ratio,
        "mean_region_ratio": mean_region_ratio,
        "mean_delta": mean_delta,
        "max_delta": max_delta,
        "width_ratio": float(current_w / max(baseline_w, 1)),
        "height_ratio": float(current_h / max(baseline_h, 1)),
    }


def feature_vector_from_result(result: CompareResult) -> np.ndarray:
    feature_dict = extract_rule_feature_dict(result)
    return np.asarray([feature_dict[name] for name in RULE_FEATURE_NAMES], dtype=np.float32)


def stack_feature_rows(rows: Iterable[np.ndarray]) -> np.ndarray:
    arrays = [np.asarray(row, dtype=np.float32) for row in rows]
    if not arrays:
        raise ValueError("No feature rows provided")
    return np.stack(arrays, axis=0)


def prepare_image_for_backbone(image: np.ndarray, image_size: int = DEFAULT_IMAGE_SIZE) -> np.ndarray:
    if image is None:
        raise ValueError("image cannot be None")
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("Expected HxWx3 image input")

    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    resized = cv2.resize(rgb, (image_size, image_size), interpolation=cv2.INTER_AREA)
    return resized.astype(np.uint8)


def normalize_batch_uint8(batch: np.ndarray) -> np.ndarray:
    if batch.ndim != 4 or batch.shape[-1] != 3:
        raise ValueError("Expected NHWC uint8 batch")
    batch_float = batch.astype(np.float32) / 255.0
    batch_float = (batch_float - IMAGENET_MEAN.reshape(1, 1, 1, 3)) / IMAGENET_STD.reshape(1, 1, 1, 3)
    return np.transpose(batch_float, (0, 3, 1, 2)).astype(np.float32)


def ensure_rgb_batch(images: Sequence[np.ndarray], image_size: int = DEFAULT_IMAGE_SIZE) -> np.ndarray:
    if not images:
        raise ValueError("At least one image is required")
    prepared = [prepare_image_for_backbone(image, image_size=image_size) for image in images]
    return np.stack(prepared, axis=0)


def compute_image_ahash(image: np.ndarray) -> int:
    """Compute 64-bit Average Hash for a BGR/RGB/Gray numpy image."""
    if image is None:
        return 0
    if image.ndim == 3:
        if image.shape[2] == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        elif image.shape[2] == 4:
            gray = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
        else:
            gray = image[:, :, 0]
    else:
        gray = image
    resized = cv2.resize(gray, (8, 8), interpolation=cv2.INTER_AREA)
    std = np.std(resized)
    if std < 1.0:
        return 0
    mean = np.mean(resized)
    hash_val = 0
    for i, val in enumerate(resized.flatten()):
        if val >= mean:
            hash_val |= (1 << i)
    return hash_val



def are_images_identical_hash(image_a: np.ndarray, image_b: np.ndarray, threshold: int = 2) -> bool:
    """Return True if images are perceptually identical based on Average Hash Hamming distance."""
    if image_a is None or image_b is None:
        return False
    if image_a.shape != image_b.shape:
        return False
    hash_a = compute_image_ahash(image_a)
    hash_b = compute_image_ahash(image_b)
    diff = hash_a ^ hash_b
    distance = bin(diff).count('1')
    return distance <= threshold



# ---------------------------------------------------------------------------
# Pixel-derived structural signals
# ---------------------------------------------------------------------------
#
# Without a DOM the model receives the nine RULE_FEATURE_NAMES and 53 zeros, and
# every one of those nine measures *how much* changed — none of them says what
# kind of change it was. That is why the screenshot-only classifier cannot tell
# a recolour from a truncation: the information is not in its input.
#
# The rule engine reads those distinctions from the DOM. Most of them have a
# pixel equivalent that survives when the DOM does not:
#
#   an element moved     -> the content below it is translated by a constant
#                           offset, which phase correlation recovers directly
#   a colour changed     -> hue shifts inside the region while its edges stay put
#   a font changed       -> stroke and edge statistics change while hue does not
#   text was truncated   -> text-like density drops on one side of the region
#   an element vanished  -> the region collapses toward a flat background colour
#
# These are computed from the two crops the model is already given, so they cost
# one pass of cheap OpenCV per sample and no extra backbone time.
PIXEL_STRUCT_FEATURE_NAMES = [
    "px_translate_y",          # vertical offset that best aligns the pair (normalised)
    "px_translate_x",
    "px_translate_conf",       # how strongly that offset is supported
    "px_hue_shift",            # mean hue rotation inside the changed area
    "px_sat_shift",
    "px_value_shift",
    "px_edge_density_delta",   # stroke/outline change: font substitution
    "px_edge_orientation_delta",
    "px_ink_ratio_delta",      # text-like coverage: truncation removes ink
    "px_flatness_delta",       # collapse toward a flat fill: element removed
    "px_bbox_fill_ratio",      # how much of the crop the change occupies
    "px_change_aspect",        # wide-and-short (a line of text) vs blocky
]

FULL_FEATURE_NAMES_V2 = FULL_FEATURE_NAMES + PIXEL_STRUCT_FEATURE_NAMES


def _to_gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def pixel_struct_feature_vector(baseline: "np.ndarray | None", current: "np.ndarray | None") -> np.ndarray:
    """Describe *what kind* of change the two crops show, not just how much.

    Returns zeros when the crops are missing or unusable, matching how the DOM
    blocks behave when there is no sidecar — a model trained with this block can
    still be given nothing and will simply see no evidence.
    """
    n = len(PIXEL_STRUCT_FEATURE_NAMES)
    if baseline is None or current is None:
        return np.zeros(n, dtype=np.float32)
    try:
        if baseline.shape != current.shape:
            h = min(baseline.shape[0], current.shape[0])
            w = min(baseline.shape[1], current.shape[1])
            if h < 8 or w < 8:
                return np.zeros(n, dtype=np.float32)
            baseline, current = baseline[:h, :w], current[:h, :w]
        h, w = baseline.shape[:2]
        if h < 8 or w < 8:
            return np.zeros(n, dtype=np.float32)

        # Measure inside the change, not across the page. A recolour touches a
        # few hundred glyph pixels out of a million; averaged over the whole
        # image every one of these statistics collapses to zero and the classes
        # become indistinguishable — measured, and the reason an earlier version
        # of this function separated nothing. Phase correlation is the exception
        # and stays global, because a layout shift is a property of the page.
        full_gb, full_gc = _to_gray(baseline), _to_gray(current)
        _d = cv2.absdiff(full_gb, full_gc)
        _ys, _xs = np.nonzero(_d > 8)
        if _ys.size:
            pad = 8
            y0, y1 = max(0, int(_ys.min()) - pad), min(h, int(_ys.max()) + 1 + pad)
            x0, x1 = max(0, int(_xs.min()) - pad), min(w, int(_xs.max()) + 1 + pad)
            if (y1 - y0) >= 8 and (x1 - x0) >= 8:
                baseline = baseline[y0:y1, x0:x1]
                current = current[y0:y1, x0:x1]
        gb, gc = _to_gray(baseline), _to_gray(current)

        # --- translation: a layout shift moves content by a constant offset ---
        try:
            (dx, dy), conf = cv2.phaseCorrelate(full_gb.astype(np.float32), full_gc.astype(np.float32))
            translate_x = float(np.clip(dx / max(w, 1), -1.0, 1.0))
            translate_y = float(np.clip(dy / max(h, 1), -1.0, 1.0))
            translate_conf = float(np.clip(conf, 0.0, 1.0))
        except Exception:
            translate_x = translate_y = translate_conf = 0.0

        # --- colour: hue moves, geometry does not ---
        if baseline.ndim == 3 and current.ndim == 3:
            hb = cv2.cvtColor(baseline, cv2.COLOR_BGR2HSV).astype(np.float32)
            hc = cv2.cvtColor(current, cv2.COLOR_BGR2HSV).astype(np.float32)
            changed = np.abs(gc.astype(np.int16) - gb.astype(np.int16)) > 8
            if changed.any():
                hue_shift = float(np.mean(np.abs(hc[..., 0][changed] - hb[..., 0][changed])) / 180.0)
                sat_shift = float(np.mean(np.abs(hc[..., 1][changed] - hb[..., 1][changed])) / 255.0)
                val_shift = float(np.mean(np.abs(hc[..., 2][changed] - hb[..., 2][changed])) / 255.0)
            else:
                hue_shift = sat_shift = val_shift = 0.0
        else:
            hue_shift = sat_shift = val_shift = 0.0

        # --- strokes: a font substitution changes edges, not colour ---
        eb, ec = cv2.Canny(gb, 60, 160), cv2.Canny(gc, 60, 160)
        edge_b, edge_c = float(eb.mean()) / 255.0, float(ec.mean()) / 255.0
        edge_density_delta = edge_c - edge_b

        def _orientation(gray):
            gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
            gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
            mag = np.abs(gx).sum() + np.abs(gy).sum()
            return float(np.abs(gx).sum() / mag) if mag > 0 else 0.5
        edge_orientation_delta = _orientation(gc) - _orientation(gb)

        # --- ink: truncation removes text, leaving background ---
        def _ink(gray):
            thr = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C,
                                        cv2.THRESH_BINARY_INV, 15, 10)
            return float(thr.mean()) / 255.0
        ink_b, ink_c = _ink(gb), _ink(gc)
        ink_ratio_delta = ink_c - ink_b

        # --- flatness: a removed element leaves a uniform fill ---
        flatness_delta = float(gc.std() - gb.std()) / 128.0

        # --- geometry of the change itself ---
        diff = cv2.absdiff(gb, gc)
        ys, xs = np.nonzero(diff > 8)
        if ys.size:
            bh = float(ys.max() - ys.min() + 1)
            bw = float(xs.max() - xs.min() + 1)
            bbox_fill = float(ys.size) / max(bw * bh, 1.0)
            aspect = bw / max(bh, 1.0)
            change_aspect = float(np.clip(np.log1p(aspect) / 4.0, 0.0, 1.0))
        else:
            bbox_fill = change_aspect = 0.0

        values = [
            translate_y, translate_x, translate_conf,
            hue_shift, sat_shift, val_shift,
            edge_density_delta, edge_orientation_delta,
            ink_ratio_delta, flatness_delta,
            bbox_fill, change_aspect,
        ]
        out = np.asarray(values, dtype=np.float32)
        return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)
    except Exception:
        return np.zeros(n, dtype=np.float32)


def rule_feature_stats(rows: "np.ndarray") -> "tuple[np.ndarray, np.ndarray]":
    """Per-feature mean and standard deviation for standardising the rule vector.

    Constant columns get a std of 1 so standardising leaves them at zero rather
    than dividing by nothing — width_ratio and height_ratio are exactly 1.0 on
    every same-size comparison, which is all of them.
    """
    rows = np.asarray(rows, dtype=np.float32)
    mean = rows.mean(axis=0)
    std = rows.std(axis=0)
    std[std < 1e-6] = 1.0
    return mean.astype(np.float32), std.astype(np.float32)


def standardise_rule_vector(vec: "np.ndarray", mean, std) -> "np.ndarray":
    """Put every rule feature on a comparable scale before the fusion layer.

    Measured on this project's captures, the raw features span a standard
    deviation ratio of 2.4e10: max_delta varies by ~24 while px_translate_x
    varies by ~0.003. Concatenated straight onto an 8192-wide image embedding
    and fed to a single Linear, the small-scale columns cannot move the output
    enough for gradient descent to find them — which is why zeroing the entire
    53-column DOM block changed the network's predictions not at all, while a
    gradient-boosted tree over the same features (scale-invariant by
    construction) reached 66.7% where the network reached 36.0%.

    Applied identically at training and inference; the statistics travel in the
    checkpoint so the two cannot disagree. A model saved without them is left
    untouched, keeping its original behaviour.
    """
    if mean is None or std is None:
        return vec
    vec = np.asarray(vec, dtype=np.float32)
    mean = np.asarray(mean, dtype=np.float32)
    std = np.asarray(std, dtype=np.float32)
    width = vec.shape[-1]
    if mean.shape[-1] != width or std.shape[-1] != width:
        # A checkpoint whose stats predate a feature block: standardise the
        # columns it knows and leave the rest, rather than refusing outright.
        n = min(width, mean.shape[-1], std.shape[-1])
        out = np.array(vec, dtype=np.float32, copy=True)
        out[..., :n] = (out[..., :n] - mean[:n]) / std[:n]
        return out
    return (vec - mean) / std
