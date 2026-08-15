"""Suggest ignore regions for content that genuinely changes on every capture.

The thing worth ignoring is dynamic content: an ad slot, a clock, a rotating
carousel, a "12 minutes ago" timestamp. What distinguishes it from a regression
is not that it keeps showing up in the diff — a bug nobody has fixed does that
too — but that *what it shows is different every time*. The first version of
this module only clustered repeating diff regions, so on a page whose only
recurring difference was the injected defect it proposed ignoring 57% of the
page, defect included. Ignoring that would have switched the case off for good.

So a candidate has to clear three gates:

  1. it shows up in nearly every recent run, not just the failing ones (a
     regression starts at some point in history; dynamic content has always
     been there),
  2. the pixels inside it differ from run to run (a regression renders the
     same wrong thing every time),
  3. it is small enough to plausibly be a widget rather than the page.

Anything that repeats but renders identically is reported back as skipped with
its reason, because "this same area changed in 4 of 5 runs" is worth telling a
reviewer — as a likely unfixed regression, not as something to mask.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .config import resolve_image_path
from .review_manager import ReviewManager

logger = logging.getLogger(__name__)

Box = Tuple[int, int, int, int]

# Two boxes are the same widget if they overlap this much. Compared against a
# cluster's representative box rather than any member, so clusters cannot creep
# across the page by chaining partial overlaps.
MIN_IOU = 0.5
# Dynamic content is present in every capture — but "every" needs slack. An ad
# slot with five creatives serves the baseline's own creative about one run in
# five, and that run comes back pixel-identical. Measured on a real rotating ad:
# 3 of 4 runs. So allow a proportional number of misses, never fewer than one.
MIN_APPEARANCE_RATE = 0.8
# Mean absolute difference between run crops, normalised to 0..1. Re-encoding
# and anti-aliasing move this by well under 0.01; an ad or a clock moves it by
# an order of magnitude more.
MIN_CONTENT_VARIABILITY = 0.03
# A suggestion covering more of the page than this is masking the page, not a
# widget on it.
MAX_AREA_FRACTION = 0.25
# How much bigger a run's region may be than a cluster and still count as the
# same widget swallowed by a larger change.
MAX_CONTAINER_RATIO = 4.0
# Downscaled crop size used for the run-to-run comparison.
_SIGNATURE_SIZE = 32


def _iou(a: Box, b: Box) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    inter = max(0, right - left) * max(0, bottom - top)
    union = aw * ah + bw * bh - inter
    if union <= 0:
        return 0.0
    return inter / union


def _matches(cluster_box: Box, box: Box) -> bool:
    """Does `box` describe the same thing the cluster is tracking?

    Overlap alone is the usual test. The extra containment case covers a run in
    which the widget's diff got merged with a change next to it: the widget is
    still in there, and refusing to count it would make an always-changing
    region look intermittent. The size ceiling stops one page-sized region from
    corroborating every cluster on the page.
    """
    if _iou(cluster_box, box) >= MIN_IOU:
        return True
    cx, cy, cw, ch = cluster_box
    bx, by, bw, bh = box
    inter = max(0, min(cx + cw, bx + bw) - max(cx, bx)) * max(0, min(cy + ch, by + bh) - max(cy, by))
    cluster_area = cw * ch
    if not cluster_area:
        return False
    return inter / cluster_area >= 0.9 and (bw * bh) <= cluster_area * MAX_CONTAINER_RATIO


def _median_box(boxes: Sequence[Box]) -> Box:
    """Representative box for a cluster.

    The median rather than the bounding box: one run that merged the widget
    with a neighbouring change should not drag the suggestion out over the
    neighbour.
    """
    xs = sorted(b[0] for b in boxes)
    ys = sorted(b[1] for b in boxes)
    ws = sorted(b[2] for b in boxes)
    hs = sorted(b[3] for b in boxes)
    mid = len(boxes) // 2
    return (xs[mid], ys[mid], ws[mid], hs[mid])


def _load_boxes(payload: Dict[str, Any]) -> List[Box]:
    boxes: List[Box] = []
    for r in (payload.get("result") or {}).get("regions") or []:
        x = r.get("x")
        y = r.get("y")
        w = r.get("width") or r.get("w")
        h = r.get("height") or r.get("h")
        if x is None or y is None or not w or not h:
            continue
        boxes.append((int(x), int(y), int(w), int(h)))
    return boxes


def _crop_signature(image: np.ndarray, box: Box) -> Optional[np.ndarray]:
    """Downscaled crop, or None if the box falls outside the image.

    Colour is kept. Swapping one ad creative for another is largely a colour
    change, and two creatives that differ obviously to a reader can sit at
    nearly the same luminance: on a real rotating ad, greyscale scored the
    swap at 0.05 and colour at 0.32.
    """
    x, y, w, h = box
    ih, iw = image.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(iw, x + w), min(ih, y + h)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    crop = image[y0:y1, x0:x1]
    return cv2.resize(crop, (_SIGNATURE_SIZE, _SIGNATURE_SIZE), interpolation=cv2.INTER_AREA).astype(np.float32)


def _variability(signatures: Sequence[np.ndarray]) -> float:
    """Mean pairwise difference between crops, 0 (identical) to 1."""
    if len(signatures) < 2:
        return 0.0
    diffs = [
        float(np.mean(np.abs(signatures[i] - signatures[j]))) / 255.0
        for i in range(len(signatures))
        for j in range(i + 1, len(signatures))
    ]
    return sum(diffs) / len(diffs)


def _recent_run_ids(store, baseline_name: str, current_run_id: str, limit: int) -> List[str]:
    """The most recent runs of this baseline, whatever their status.

    Passing runs matter: they are the evidence that a region is *not* dynamic.
    Regions are recorded for every comparison, so a run that came back with
    none is a run in which that area did not move.
    """
    is_pg = hasattr(store, "pool")
    placeholder = "%s" if is_pg else "?"
    query = f"""
        SELECT run_id FROM runs_index
        WHERE baseline_name = {placeholder} AND run_id != {placeholder}
        ORDER BY created_at DESC LIMIT {placeholder};
    """
    try:
        rows = store._execute_query(query, (baseline_name, current_run_id, limit), fetch=True)
    except Exception as e:
        logger.warning("Failed to query runs for auto-ignore suggestions: %s", e)
        return []
    return [row["run_id"] for row in rows]


def get_auto_ignore_suggestions(
    store, paths, baseline_name: str, current_run_id: str, limit: int = 5
) -> List[Dict[str, Any]]:
    """Regions that look like dynamic content across the last `limit` runs.

    Each suggestion carries the evidence behind it (`appearance_rate`,
    `variability`) so the dashboard can show why it is being proposed.
    """
    accepted, _ = analyze_repeating_regions(store, paths, baseline_name, current_run_id, limit)
    return accepted


def analyze_repeating_regions(
    store, paths, baseline_name: str, current_run_id: str, limit: int = 5
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (suggested, skipped) regions, both with their reasons."""
    run_ids = _recent_run_ids(store, baseline_name, current_run_id, limit)
    if not run_ids:
        return [], []

    manager = ReviewManager(paths)
    per_run_boxes: List[List[Box]] = []
    per_run_dir: List[Path] = []
    page_area = 0

    for rid in run_ids:
        try:
            run_dir = manager.resolve_run_dir(rid)
            payload = manager.load_run_payload(run_dir)
        except Exception as e:
            logger.warning("Failed to load run payload for %s: %s", rid, e)
            continue
        size = (payload.get("result") or {}).get("current_size") or []
        if len(size) == 2 and size[0] and size[1]:
            area = int(size[0]) * int(size[1])
            # Runs captured at another viewport describe a different coordinate
            # space; their boxes cannot be compared with these.
            if page_area and area != page_area:
                continue
            page_area = page_area or area
        per_run_boxes.append(_load_boxes(payload))
        per_run_dir.append(run_dir)

    runs_examined = len(per_run_boxes)
    if runs_examined < 2:
        return [], []

    # Greedy clustering against each cluster's representative box: a box joins
    # the first cluster it actually overlaps, and only boxes from other runs
    # can extend a cluster.
    clusters: List[Dict[str, Any]] = []
    for run_idx, boxes in enumerate(per_run_boxes):
        for box in boxes:
            for cluster in clusters:
                if run_idx in cluster["runs"]:
                    continue
                if _matches(cluster["box"], box):
                    cluster["members"].append((run_idx, box))
                    cluster["runs"].add(run_idx)
                    cluster["box"] = _median_box([b for _, b in cluster["members"]])
                    break
            else:
                clusters.append({"box": box, "members": [(run_idx, box)], "runs": {run_idx}})

    # Cache one decoded image per run; only clusters that survive the cheap
    # gates need pixels at all.
    image_cache: Dict[int, Optional[np.ndarray]] = {}

    def image_for(run_idx: int) -> Optional[np.ndarray]:
        if run_idx not in image_cache:
            path = resolve_image_path(per_run_dir[run_idx], "current")
            img = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.exists() else None
            if img is None:
                logger.info("No readable current image for %s; cannot judge variability", per_run_dir[run_idx].name)
            image_cache[run_idx] = img
        return image_cache[run_idx]

    suggested: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for cluster in clusters:
        box = cluster["box"]
        frequency = len(cluster["runs"])
        appearance_rate = frequency / runs_examined
        record = {
            "x": box[0],
            "y": box[1],
            "width": box[2],
            "height": box[3],
            "frequency": frequency,
            "total_runs_analyzed": runs_examined,
            "appearance_rate": round(appearance_rate, 3),
        }

        allowed_misses = max(1, round(runs_examined * (1.0 - MIN_APPEARANCE_RATE)))
        if frequency < 2:
            continue
        if runs_examined - frequency > allowed_misses:
            skipped.append({**record, "reason": "appears-in-some-runs-only",
                            "detail": f"Changed in {frequency} of {runs_examined} recent runs — not every capture."})
            continue
        if page_area and (box[2] * box[3]) / page_area > MAX_AREA_FRACTION:
            skipped.append({**record, "reason": "too-large",
                            "detail": f"Covers {round(box[2] * box[3] / page_area * 100)}% of the page — too large to be dynamic content."})
            continue

        signatures = []
        for run_idx, _ in cluster["members"]:
            img = image_for(run_idx)
            if img is None:
                continue
            sig = _crop_signature(img, box)
            if sig is not None:
                signatures.append(sig)

        if len(signatures) < 2:
            skipped.append({**record, "reason": "no-evidence",
                            "detail": "Screenshots for these runs are unavailable, so the content could not be checked."})
            continue

        variability = _variability(signatures)
        record["variability"] = round(variability, 4)
        if variability < MIN_CONTENT_VARIABILITY:
            skipped.append({**record, "reason": "stable-content",
                            "detail": "Renders the same in every run — this looks like an unfixed change, not dynamic content."})
            continue

        suggested.append({**record, "reason": "dynamic-content",
                          "detail": f"Changed in {frequency} of {runs_examined} runs and rendered differently each time."})

    suggested.sort(key=lambda s: s["variability"], reverse=True)
    return suggested, skipped
