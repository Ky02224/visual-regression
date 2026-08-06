"""
Blind live-DOM robustness test — the sequel to random_mutation_eval.py.

random_mutation_eval.py mutates *pixels* on static demo_portal screenshots.
It never exercises the DOM-diff classifier (visual_regression.ai_features.
diagnose_from_dom_diff) added this session, because there is no live browser
DOM behind a pixel-only mutation, and it only ever tests demo_portal, which
has a hardcoded signature shortcut (_detect_demo_portal_defect) that would
make any accuracy number partly circular.

This script instead: loads real pages in a real browser, applies a randomized
*structural* mutation directly to the live DOM (remove a node, move it, change
its computed font/color, truncate its text), recaptures, and runs the exact
same compare_arrays() + assess_result() pipeline production uses -- including
writing real .dom.json sidecars next to the images, exactly like browser.py
does during a real capture. Sites are real, external, third-party pages this
project has never trained on, so this measures actual day-one generalization.

Usage:
    python scripts/live_dom_mutation_eval.py --trials 40 --seed 20260728
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("VRT_DISABLE_AI_SPLIT", "true")

import cv2
import numpy as np
from playwright.sync_api import sync_playwright

from visual_regression.browser import _CAPTURE_DOM_SNAPSHOT_JS
from visual_regression.config import WorkspacePaths
from visual_regression.image_compare import compare_arrays
from visual_regression.ai_training import assess_result, _consolidate_label

SITES = [
    "https://news.ycombinator.com/",
    "https://en.wikipedia.org/wiki/Web_browser",
    "https://docs.python.org/3/tutorial/introduction.html",
    "https://books.toscrape.com/",
    "https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/div",
    "https://old.reddit.com/",
]
# Previously included github.com/torvalds/linux/blob/master/README, but its
# live star/watch counters and relative timestamps ("X days ago") change
# between the baseline and current capture even with zero mutation applied —
# confirmed by two trials against it reporting the exact same mismatch_pct
# (17.8082%) despite one being a "benign" (unmutated) trial. That's a false
# positive baked into the site choice, not a model error, so it inflates
# the error count without measuring anything real.

CATEGORIES = [
    "benign",
    "missing-element",
    "layout-issue",
    "color-regression",
    "font-change",
    "broken-image",
    "text-issue",
]

_VISIBLE_CHECK_JS = """
    function isActuallyVisible(el, r) {
        // A real, non-zero getBoundingClientRect is not proof an element is
        // actually rendered on screen — a collapsed accordion/sidebar panel
        // (e.g. Wikipedia's collapsed right-side "Tools" menu) keeps valid
        // layout coordinates for its children even while invisible, clipped
        // by an ancestor's overflow:hidden or width:0 collapse. Sampling
        // whether the element (or a descendant, for e.g. an <a> wrapping
        // more markup) is actually the thing painted at its own center point
        // catches this the same way a real user's eyes would, instead of
        // trusting layout geometry alone.
        const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
        const hit = document.elementFromPoint(cx, cy);
        return !!hit && (hit === el || el.contains(hit) || hit.contains(el));
    }
"""

_LEAF_CHECK_JS = """
    function ownsItsText(el) {
        // A wrapper span/li with element children (e.g. HN's
        // <span class="titleline"><a>Title</a><span>(site.com)</span></span>)
        // renders no text of its own — every visible pixel belongs to a
        // child that carries its OWN color/font (from the site's CSS, e.g.
        // a:link { color }), which wins over anything inherited from this
        // wrapper regardless of what style is set on it. Setting
        // color/fontFamily here is confirmed to produce a real DOM/
        // computed-style change with zero rendered pixels (verified: full
        // before/after screenshots byte-identical despite getComputedStyle
        // correctly reporting the new color) — not a browser timing bug,
        // just mutating an element that owns no visible text. Only
        // elements whose own direct child nodes include real text qualify.
        return Array.from(el.childNodes).some(n => n.nodeType === 3 && n.textContent.trim().length > 0);
    }
"""

_COUNT_JS = """
([tags, requireBlock, requireLeaf]) => {
    """ + _VISIBLE_CHECK_JS + _LEAF_CHECK_JS + """
    const els = Array.from(document.querySelectorAll(tags.join(',')));
    const candidates = els.filter(el => {
        const r = el.getBoundingClientRect();
        if (!(r.width > 40 && r.height > 12 && r.top >= 0 && r.top < 700 && r.left >= 0)) return false;
        // scrollWidth/clientWidth are always 0 on display:inline elements
        // (a browser-level rule, not a capture bug) — and CSS truncation
        // (text-overflow/overflow/white-space) is a no-op on inline
        // elements too, so a plain inline <span>/<a> can never realistically
        // be a truncation target in production either. Restricting to
        // already block-ish elements keeps the picked target consistent
        // between the baseline and mutated capture, matching how a real
        // truncation defect actually looks.
        if (requireBlock && getComputedStyle(el).display === 'inline') return false;
        // requireBlock is also the text-issue signal, and text-issue
        // additionally needs a plain single/double-line text element, not
        // a large tile-shaped <a>/<li> wrapping an image + caption + more
        // (real pages commonly wrap rich content in a block-level <a>).
        // Shrinking one of those down doesn't look like realistic text
        // truncation — it collapses/reflows the whole tile, which produces
        // a much bigger, more disruptive change than the category models.
        if (requireBlock && r.height > 40) return false;
        if (requireLeaf && !ownsItsText(el)) return false;
        return isActuallyVisible(el, r);
    });
    return candidates.length;
}
"""

_PICK_AT_INDEX_JS = """
([tags, index, requireBlock, requireLeaf]) => {
    """ + _VISIBLE_CHECK_JS + _LEAF_CHECK_JS + """
    const els = Array.from(document.querySelectorAll(tags.join(',')));
    const candidates = els.filter(el => {
        const r = el.getBoundingClientRect();
        if (!(r.width > 40 && r.height > 12 && r.top >= 0 && r.top < 700 && r.left >= 0)) return false;
        if (requireBlock && getComputedStyle(el).display === 'inline') return false;
        if (requireBlock && r.height > 40) return false;
        if (requireLeaf && !ownsItsText(el)) return false;
        return isActuallyVisible(el, r);
    });
    if (index >= candidates.length) return null;
    candidates[index].setAttribute('data-vrt-mutated', '1');
    return true;
}
"""

MUTATION_JS = {
    "benign": """
        () => { document.body.setAttribute('data-vrt-noop', String(Math.random())); return {ok: true}; }
    """,
    "missing-element": """
        () => {
            const el = document.querySelector('[data-vrt-mutated]');
            if (!el) return null;
            const r = el.getBoundingClientRect();
            // Whether an image goes with it decides the label. The picker
            // chooses from p/span/a/div/li, and on real pages those routinely
            // wrap a thumbnail — <a><img></a> is the standard card and nav
            // pattern. Removing the wrapper takes the image off the page, and
            // no comparison of two snapshots can tell that apart from removing
            // the image itself: both leave an <img> present before and absent
            // after. Reporting it lets the label describe what a viewer lost
            // rather than which node the script happened to pick.
            const media = el.matches('img,svg,video,canvas,picture')
                || !!el.querySelector('img,svg,video,canvas,picture');
            const info = {tag: el.tagName, x: r.x, y: r.y, w: r.width, h: r.height,
                          tookMedia: media};
            el.remove();
            return info;
        }
    """,
    "layout-issue": """
        () => {
            const el = document.querySelector('[data-vrt-mutated]');
            if (!el) return null;
            const cs = getComputedStyle(el);
            if (cs.position === 'static') el.style.position = 'relative';
            el.style.left = '45px';
            el.style.top = '25px';
            return {tag: el.tagName};
        }
    """,
    "color-regression": """
        () => {
            const el = document.querySelector('[data-vrt-mutated]');
            if (!el) return null;
            el.style.color = 'rgb(220, 20, 20)';
            return {tag: el.tagName};
        }
    """,
    "font-change": """
        () => {
            const el = document.querySelector('[data-vrt-mutated]');
            if (!el) return null;
            el.style.fontFamily = "'Courier New', monospace";
            return {tag: el.tagName};
        }
    """,
    "broken-image": """
        () => {
            const el = document.querySelector('[data-vrt-mutated]');
            if (!el) return null;
            el.remove();
            return {tag: el.tagName};
        }
    """,
    "text-issue": """
        () => {
            const el = document.querySelector('[data-vrt-mutated]');
            if (!el) return null;
            // A fraction of the original width (e.g. 35%) only forces
            // visible clipping if the text was already filling most of
            // that width — plenty of real candidates (a short link inside
            // a wide box) have room to spare, so shrinking proportionally
            // can shed almost no visible characters (confirmed: "Upload
            // file" at 186px -> 65px produced a near-zero pixel diff,
            // since 65px was still enough to render the whole word). A
            // small fixed width forces real clipping regardless of how
            // much slack the original box had, as long as there's more
            // than a couple characters of text to cut off — the pick
            // filter already requires width > 40, so real content is
            // there to clip.
            el.style.width = '28px';
            el.style.overflow = 'hidden';
            el.style.whiteSpace = 'nowrap';
            el.style.textOverflow = 'clip';
            return {tag: el.tagName};
        }
    """,
}

PICK_TAGS = {
    "missing-element": ['p', 'span', 'a', 'button', 'h1', 'h2', 'h3', 'li', 'div'],
    "layout-issue": ['p', 'span', 'a', 'h1', 'h2', 'h3', 'li'],
    "color-regression": ['p', 'span', 'a', 'h1', 'h2', 'h3', 'li'],
    "font-change": ['p', 'span', 'a', 'h1', 'h2', 'h3', 'li'],
    "broken-image": ['img'],
    "text-issue": ['p', 'span', 'a', 'li'],
}


def to_consolidated(name: str) -> str:
    if name in {"benign", "no-change", ""}:
        name = "insignificant-change"
    return _consolidate_label(name)


def run_trial(page, url: str, category: str, rng: random.Random, tmp_dir: Path, idx: int):
    page.goto(url, wait_until="networkidle", timeout=25000)
    # A custom webfont that finishes loading between the baseline and
    # current capture changes text metrics (fallback-font width vs
    # final-font width) for elements nowhere near the actual mutation —
    # confirmed on a real site: an unrelated button's scrollWidth grew
    # 100px -> 131px between two captures with identical layout/position,
    # purely from a font swap, misreported as a genuine text-issue. Baseline
    # must wait for fonts to settle so "nothing but the mutation changed"
    # actually holds.
    try:
        page.evaluate("() => document.fonts.ready")
    except Exception:
        pass
    page.wait_for_timeout(150)
    baseline_png = page.screenshot(full_page=False)
    baseline_dom = page.evaluate(_CAPTURE_DOM_SNAPSHOT_JS)
    # Halt the page's own background activity (ad refreshes, carousels,
    # analytics-driven DOM pokes, lazy-load timers) so the only difference
    # between baseline and current is the mutation applied below, not the
    # live site quietly changing itself in the gap between the two captures.
    try:
        page.evaluate("window.stop()")
    except Exception:
        pass

    mutated_info = None
    if category != "benign":
        tags = PICK_TAGS.get(category, ['p', 'span', 'a'])
        require_block = category == "text-issue"
        require_leaf = category in ("color-regression", "font-change")
        count = page.evaluate(_COUNT_JS, [tags, require_block, require_leaf])
        if not count:
            return None  # no suitable element on this page for this category; skip trial
        index = rng.randrange(count)  # seeded by --seed, unlike the JS-side Math.random() this replaces
        picked = page.evaluate(_PICK_AT_INDEX_JS, [tags, index, require_block, require_leaf])
        if not picked:
            return None
        mutated_info = page.evaluate(MUTATION_JS[category])
        if mutated_info is None:
            return None
    else:
        page.evaluate(MUTATION_JS["benign"])

    # A style/structure-only mutation (color change, or el.remove() when the
    # freed space needs no new content to draw into it) can update the
    # CSSOM/DOM instantly without the compositor having actually repainted
    # before screenshot() grabs the frame buffer — a fixed wait_for_timeout
    # alone isn't a guarantee, and even two animation frames still leaves a
    # visible slice of these cases stale (confirmed by inspecting saved
    # baseline/current pairs that came back byte-identical despite a real,
    # confirmed-in-the-DOM removal). Forcing a synchronous layout read
    # between animation frames, and waiting on more of them, gives Chromium
    # more chances to actually flush the composited frame.
    # Even the rAF+timeout dance above still leaves some fraction of
    # captures stale (confirmed via byte-identical baseline/current pairs
    # for structural mutations that definitely changed the DOM). Rather
    # than trying to guess a longer fixed wait that still isn't a
    # guarantee, retry the screenshot itself: a genuinely-flushed frame is
    # a fixed point (re-shooting it again won't un-flush it), so on a
    # stale hit, waiting more and re-shooting either recovers the real
    # frame or — for the rarer case where the mutation truly produced no
    # visible pixels (e.g. a collapsed/hidden element) — converges to the
    # same all-identical result the first shot already got, which is the
    # correct outcome for that case.
    # The single fonts.ready wait before the baseline capture isn't
    # sufficient on its own: window.stop() right after that wait can abort
    # an in-flight font fetch, which the browser then quietly resumes/
    # retries later — so a font can still swap in between the baseline and
    # current capture despite both waits having "passed" fonts.ready at the
    # time each ran. A second check right before shooting current, applied
    # even for unrelated elements nowhere near the mutation, is what
    # actually confirmed and fixed the "File a ticket" button case above.
    try:
        page.evaluate("() => document.fonts.ready")
    except Exception:
        pass
    baseline_arr = cv2.imdecode(np.frombuffer(baseline_png, np.uint8), cv2.IMREAD_COLOR)
    current_png = None
    for _attempt in range(4):
        page.evaluate("() => document.documentElement.getBoundingClientRect()")
        for _ in range(4):
            page.evaluate("() => new Promise(r => requestAnimationFrame(r))")
        page.wait_for_timeout(300)
        candidate_png = page.screenshot(full_page=False)
        candidate_arr = cv2.imdecode(np.frombuffer(candidate_png, np.uint8), cv2.IMREAD_COLOR)
        current_png = candidate_png
        if category == "benign" or mutated_info is None:
            break
        if not np.array_equal(baseline_arr, candidate_arr):
            break
    current_dom = page.evaluate(_CAPTURE_DOM_SNAPSHOT_JS)

    baseline_path = tmp_dir / f"baseline_{idx}.png"
    current_path = tmp_dir / f"current_{idx}.png"
    baseline_path.write_bytes(baseline_png)
    current_path.write_bytes(current_png)
    baseline_path.with_suffix(".dom.json").write_text(json.dumps(baseline_dom), encoding="utf-8")
    current_path.with_suffix(".dom.json").write_text(json.dumps(current_dom), encoding="utf-8")

    current_img = cv2.imdecode(np.frombuffer(current_png, np.uint8), cv2.IMREAD_COLOR)
    result, _, _ = compare_arrays(
        baseline=baseline_arr, current=current_img,
        pixel_threshold=20, min_region_area=120, ignore_regions=[],
    )
    return result, baseline_path, current_path, mutated_info


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=40)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--model-path", type=str, default=None)
    parser.add_argument("--out", type=str, default=None)
    args = parser.parse_args()

    seed = args.seed if args.seed is not None else int(time.time() * 1000) % (2**31)
    rng = random.Random(seed)
    print(f"Random seed: {seed}")

    paths = WorkspacePaths(root=ROOT / ".visual-regression")
    model_path = Path(args.model_path) if args.model_path else paths.models_dir / "visual_ai.pt"
    print(f"Model: {model_path}")

    tmp_dir = paths.root / "tmp-live-dom-eval"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        i = 0
        attempts = 0
        while i < args.trials and attempts < args.trials * 3:
            attempts += 1
            url = rng.choice(SITES)
            category = rng.choice(CATEGORIES)
            try:
                out = run_trial(page, url, category, rng, tmp_dir, i)
            except Exception as e:
                print(f"  [skip] {url} {category}: {e}")
                continue
            if out is None:
                continue
            result, baseline_path, current_path, mutated_info = out

            assessment = assess_result(
                result=result,
                model_path=model_path,
                baseline_image_path=baseline_path,
                current_image_path=current_path,
            )
            pred_label = assessment.label or "benign"
            # Ground truth follows the visible outcome, not the node the picker
            # chose. Removing a wrapper that contained a thumbnail takes an
            # image off the page, which is what a reviewer sees and what the
            # snapshots record; calling it "missing-element" because the script
            # deleted an <a> asked the classifier for information no comparison
            # of before and after contains. Six of 29 residual errors were this
            # one mismatch — see ADR 0006.
            expected_category = category
            if category == "missing-element" and (mutated_info or {}).get("tookMedia"):
                expected_category = "broken-image"
            expected_c = to_consolidated(expected_category)
            pred_c = to_consolidated(pred_label)
            correct = expected_c == pred_c

            record = {
                "trial": i,
                "site": url,
                "expected": expected_category,
                "requested_category": category,
                "expected_consolidated": expected_c,
                "predicted": pred_label,
                "predicted_consolidated": pred_c,
                "correct": correct,
                "mismatch_pct": result.mismatch_pct,
                "regions": len(result.regions),
                "ai_score": assessment.score,
                "ai_explanation": assessment.ai_explanation,
                "mutated": mutated_info,
            }
            results.append(record)
            mark = "OK " if correct else "ERR"
            site_short = url.split("//")[-1][:24]
            print(f"[{i+1:3d}/{args.trials}] {mark} site={site_short:24s} expected={expected_category:18s} predicted={pred_label:18s} mismatch={result.mismatch_pct:.3f}%")
            i += 1

        browser.close()

    if not results:
        print("No trials completed.")
        return

    correct_n = sum(1 for r in results if r["correct"])
    total = len(results)
    print()
    print(f"Overall accuracy: {correct_n}/{total} = {correct_n/total:.1%}")

    # Binary changed-vs-not accuracy
    binary_correct = sum(
        1 for r in results
        if (r["expected_consolidated"] != "insignificant-change") == (r["predicted_consolidated"] != "insignificant-change")
    )
    print(f"Binary (changed vs not) accuracy: {binary_correct}/{total} = {binary_correct/total:.1%}")
    print()

    by_cat = {}
    for r in results:
        by_cat.setdefault(r["expected"], []).append(r["correct"])
    print(f"{'category':22s} {'accuracy':10s} n")
    for cat in CATEGORIES:
        vals = by_cat.get(cat, [])
        if not vals:
            continue
        acc = sum(vals) / len(vals)
        print(f"{cat:22s} {acc:.1%}      {len(vals)}")

    print()
    confusion = Counter((r["expected_consolidated"], r["predicted_consolidated"]) for r in results)
    print("Confusion (expected -> predicted): count")
    for (exp, pred), cnt in sorted(confusion.items(), key=lambda kv: -kv[1]):
        flag = "" if exp == pred else "  <-- MISS"
        print(f"  {exp:22s} -> {pred:22s} : {cnt}{flag}")

    out_file = Path(args.out) if args.out else ROOT / "scratch" / "live_dom_mutation_eval_results.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps({"seed": seed, "accuracy": correct_n / total, "results": results}, indent=2), encoding="utf-8")
    print(f"\nSaved to {out_file}")


if __name__ == "__main__":
    main()
