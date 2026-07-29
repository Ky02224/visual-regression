"""
Blind randomized robustness test for the AI classifier.

Unlike run_evaluations_9classes.py (which replays a fixed, hand-authored set
of CSS-based defect classes on the demo site — classes the veto heuristics
were tuned against), this script mutates real captured screenshots directly
at the pixel level with randomized position/size/color/offset parameters
each run. Nothing here is hand-tuned to match the current heuristics, so it
is a much less circular check of real-world accuracy.

Usage:
    python scripts/random_mutation_eval.py --trials 100
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from visual_regression.config import WorkspacePaths
from visual_regression.baseline_manager import BaselineManager
from visual_regression.image_compare import compare_arrays
from visual_regression.ai_training import assess_result, _consolidate_label

PAGES = ["demo-home-en", "demo-login-en", "demo-dashboard-en"]

CATEGORIES = [
    "benign",
    "missing-element",
    "layout-shift",
    "color-regression",
    "text-truncation",
    "overlay-obstruction",
    "broken-image",
    "misaligned-fields",
    "unreadable-text",
    "font-change",
]


def _local_bg(img: np.ndarray, x: int, y: int, w: int, h: int, margin: int = 6) -> tuple:
    """Median color of a thin border strip just outside the rect (local background)."""
    h_img, w_img = img.shape[:2]
    strips = []
    top_y0 = max(0, y - margin)
    if top_y0 < y:
        strips.append(img[top_y0:y, x:min(x + w, w_img)])
    bot_y1 = min(h_img, y + h + margin)
    if bot_y1 > y + h:
        strips.append(img[y + h:bot_y1, x:min(x + w, w_img)])
    left_x0 = max(0, x - margin)
    if left_x0 < x:
        strips.append(img[y:min(y + h, h_img), left_x0:x])
    right_x1 = min(w_img, x + w + margin)
    if right_x1 > x + w:
        strips.append(img[y:min(y + h, h_img), x + w:right_x1])
    pixels = [s.reshape(-1, 3) for s in strips if s.size]
    if not pixels:
        return (255, 255, 255)
    all_px = np.concatenate(pixels, axis=0)
    return tuple(int(v) for v in np.median(all_px, axis=0))


def _has_content(img: np.ndarray, x: int, y: int, w: int, h: int, min_std: float = 8.0) -> bool:
    h_img, w_img = img.shape[:2]
    x2, y2 = min(x + w, w_img), min(y + h, h_img)
    if x2 <= x or y2 <= y:
        return False
    patch = img[y:y2, x:x2]
    return bool(np.std(patch) >= min_std)


def _pick_content_rect(img: np.ndarray, rng: random.Random, w: int, h: int, x_range: tuple, y_range: tuple, attempts: int = 25, min_std: float = 8.0) -> tuple:
    """Retry random (x, y) placements until the rect covers real content (not blank background)."""
    best = None
    for _ in range(attempts):
        x = rng.randint(*x_range)
        y = rng.randint(*y_range)
        if _has_content(img, x, y, w, h, min_std=min_std):
            return x, y
        best = (x, y)
    return best


def mutate_benign(img: np.ndarray, rng: random.Random) -> np.ndarray:
    out = img.copy()
    if rng.random() < 0.5:
        noise = np.random.default_rng(rng.randint(0, 2**31)).integers(-1, 2, out.shape, dtype=np.int16)
        out = np.clip(out.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    return out


def mutate_missing_element(img: np.ndarray, rng: random.Random) -> np.ndarray:
    out = img.copy()
    h, w = out.shape[:2]
    bw, bh = rng.randint(150, 450), rng.randint(40, 250)
    x, y = _pick_content_rect(img, rng, bw, bh, (30, max(31, w - bw - 30)), (80, max(81, h - bh - 60)))
    bg = _local_bg(img, x, y, bw, bh)
    cv2.rectangle(out, (x, y), (x + bw, y + bh), bg, thickness=-1)
    return out


def mutate_layout_shift(img: np.ndarray, rng: random.Random) -> np.ndarray:
    out = img.copy()
    h, w = out.shape[:2]
    bw, bh = rng.randint(150, 350), rng.randint(80, 200)
    x, y = _pick_content_rect(img, rng, bw, bh, (30, max(31, w - bw - 100)), (80, max(81, h - bh - 100)))
    dx = rng.choice([-1, 1]) * rng.randint(20, 60)
    dy = rng.choice([-1, 1]) * rng.randint(15, 45)
    nx = min(max(0, x + dx), w - bw)
    ny = min(max(0, y + dy), h - bh)
    patch = img[y:y + bh, x:x + bw].copy()
    bg = _local_bg(img, x, y, bw, bh)
    cv2.rectangle(out, (x, y), (x + bw, y + bh), bg, thickness=-1)
    out[ny:ny + bh, nx:nx + bw] = patch
    return out


def mutate_color_regression(img: np.ndarray, rng: random.Random) -> np.ndarray:
    out = img.copy()
    h, w = out.shape[:2]
    bw = rng.randint(int(w * 0.5), w)
    bh = rng.randint(40, 90)
    x = rng.randint(0, max(1, w - bw))
    y = rng.choice([rng.randint(0, 40), rng.randint(100, max(101, h - bh - 40))])
    region = out[y:y + bh, x:x + bw]
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV).astype(np.int16)
    hue_shift = rng.randint(50, 140)
    hsv[:, :, 0] = (hsv[:, :, 0] + hue_shift) % 180
    hsv[:, :, 1] = np.clip(hsv[:, :, 1].astype(np.int16) + 40, 0, 255)
    out[y:y + bh, x:x + bw] = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    return out


def mutate_text_truncation(img: np.ndarray, rng: random.Random) -> np.ndarray:
    out = img.copy()
    h, w = out.shape[:2]
    bh = rng.randint(16, 30)
    bw = rng.randint(150, 400)
    x, y = _pick_content_rect(
        img, rng, bw, bh,
        (int(w * 0.15), max(int(w * 0.15) + 1, w - bw - 30)),
        (100, max(101, h - bh - 60)),
        attempts=80,
        min_std=13.0,
    )
    cut_at = rng.randint(int(bw * 0.4), int(bw * 0.75))
    bg = _local_bg(img, x, y, bw, bh)
    cv2.rectangle(out, (x + cut_at, y), (x + bw, y + bh), bg, thickness=-1)
    return out


def mutate_overlay_obstruction(img: np.ndarray, rng: random.Random) -> np.ndarray:
    out = img.copy().astype(np.float32)
    h, w = out.shape[:2]
    bw = int(w * rng.uniform(0.35, 0.55))
    bh = int(h * rng.uniform(0.25, 0.45))
    x = rng.randint(int(w * 0.08), max(int(w * 0.08) + 1, w - bw - int(w * 0.08)))
    y = rng.randint(int(h * 0.08), max(int(h * 0.08) + 1, h - bh - int(h * 0.08)))
    color = np.array([rng.randint(20, 90), rng.randint(20, 90), rng.randint(20, 90)], dtype=np.float32)
    alpha = rng.uniform(0.6, 0.85)
    roi = out[y:y + bh, x:x + bw]
    out[y:y + bh, x:x + bw] = roi * (1 - alpha) + color * alpha
    return np.clip(out, 0, 255).astype(np.uint8)


def mutate_broken_image(img: np.ndarray, rng: random.Random) -> np.ndarray:
    out = img.copy()
    h, w = out.shape[:2]
    bw, bh = rng.randint(100, 220), rng.randint(70, 150)
    x = rng.randint(30, max(31, w - bw - 30))
    y = rng.randint(80, max(81, h - bh - 60))
    grey = rng.randint(190, 215)
    cv2.rectangle(out, (x, y), (x + bw, y + bh), (grey, grey, grey), thickness=-1)
    cv2.rectangle(out, (x, y), (x + bw, y + bh), (150, 150, 150), thickness=2)
    cx, cy = x + bw // 2, y + bh // 2
    s = min(bw, bh) // 4
    cv2.line(out, (cx - s, cy - s), (cx + s, cy + s), (140, 140, 140), 2)
    cv2.line(out, (cx + s, cy - s), (cx - s, cy + s), (140, 140, 140), 2)
    return out


def mutate_misaligned_fields(img: np.ndarray, rng: random.Random) -> np.ndarray:
    out = img.copy()
    h, w = out.shape[:2]
    n = rng.randint(3, 5)
    fw, fh = rng.randint(140, 220), rng.randint(24, 40)
    x0 = rng.randint(30, max(31, w - fw - 100))
    y0 = rng.randint(100, max(101, h - (fh + 20) * n - 60))
    dx = rng.choice([-1, 1]) * rng.randint(30, 70)
    for i in range(n):
        y = y0 + i * (fh + rng.randint(10, 30))
        patch = img[y:y + fh, x0:x0 + fw].copy()
        bg = _local_bg(img, x0, y, fw, fh)
        cv2.rectangle(out, (x0, y), (x0 + fw, y + fh), bg, thickness=-1)
        nx = min(max(0, x0 + dx), w - fw)
        out[y:y + fh, nx:nx + fw] = patch
    return out


def mutate_unreadable_text(img: np.ndarray, rng: random.Random) -> np.ndarray:
    h, w = img.shape[:2]
    bh = rng.randint(20, 40)
    bw = rng.randint(200, 500)
    x, y = _pick_content_rect(
        img, rng, bw, bh,
        (30, max(31, w - bw - 30)),
        (100, max(101, h - bh - 60)),
        attempts=50,
        min_std=14.0,
    )
    out = img.copy().astype(np.float32)
    target = np.array([246.0, 248.0, 246.0])
    alpha = rng.uniform(0.88, 0.98)
    roi = out[y:y + bh, x:x + bw]
    out[y:y + bh, x:x + bw] = roi * (1 - alpha) + target * alpha
    return np.clip(out, 0, 255).astype(np.uint8)


def mutate_font_change(img: np.ndarray, rng: random.Random) -> np.ndarray:
    """Simulate a CSS font-size bump: vertically upscale a content band so text
    rows grow taller, matching how the model's own training data represents
    font-change (see dataset_generator.py's font_change mode) rather than a
    subtle stroke-weight tweak the model has never actually seen."""
    h, w = img.shape[:2]
    bh = rng.randint(int(h * 0.10), int(h * 0.22))
    x1 = rng.randint(int(w * 0.03), int(w * 0.15))
    x2 = rng.randint(int(w * 0.60), int(w * 0.92))
    _, y1 = _pick_content_rect(
        img, rng, x2 - x1, bh,
        (x1, x1),
        (int(h * 0.15), max(int(h * 0.15) + 1, int(h * 0.55))),
        attempts=40,
        min_std=10.0,
    )
    y1 = min(max(0, y1), h - bh - 1)
    y2 = min(y1 + bh, h - 1)
    out = img.copy()
    region = out[y1:y2, x1:x2].copy()
    reg_h, reg_w = region.shape[:2]
    if reg_h < 10 or reg_w < 20:
        return out
    scale = rng.uniform(1.4, 1.9)
    new_h = min(int(reg_h * scale), h - y1)
    scaled = cv2.resize(region, (reg_w, new_h), interpolation=cv2.INTER_LINEAR)
    paste_h = min(scaled.shape[0], h - y1)
    out[y1:y1 + paste_h, x1:x2] = scaled[:paste_h, :]
    fill_y1 = y1 + paste_h
    fill_y2 = min(y2 + int(reg_h * (scale - 1.0)), h - 1)
    if fill_y2 > fill_y1:
        bg = _local_bg(img, x1, y1, x2 - x1, y2 - y1)
        cv2.rectangle(out, (x1, fill_y1), (x2, fill_y2), bg, thickness=-1)
    return out


MUTATORS = {
    "benign": mutate_benign,
    "missing-element": mutate_missing_element,
    "layout-shift": mutate_layout_shift,
    "color-regression": mutate_color_regression,
    "text-truncation": mutate_text_truncation,
    "overlay-obstruction": mutate_overlay_obstruction,
    "broken-image": mutate_broken_image,
    "misaligned-fields": mutate_misaligned_fields,
    "unreadable-text": mutate_unreadable_text,
    "font-change": mutate_font_change,
}


def to_consolidated(name: str) -> str:
    if name in {"benign", "no-change", ""}:
        name = "insignificant-change"
    return _consolidate_label(name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=100)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--model-path", type=str, default=None)
    parser.add_argument("--out", type=str, default=None)
    args = parser.parse_args()

    seed = args.seed if args.seed is not None else int(time.time() * 1000) % (2**31)
    rng = random.Random(seed)
    print(f"Random seed: {seed}")

    paths = WorkspacePaths(root=ROOT / ".visual-regression")
    manager = BaselineManager(paths)
    model_path = Path(args.model_path) if args.model_path else paths.models_dir / "visual_ai.pt"
    print(f"Model: {model_path}")

    baselines = {}
    for p in PAGES:
        img_path = manager.resolve_baseline_image_path(p)
        img = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(f"Could not load baseline image for {p} at {img_path}")
        baselines[p] = img

    tmp_dir = paths.root / "tmp-random-eval"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    baseline_tmp = tmp_dir / "baseline.png"
    current_tmp = tmp_dir / "current.png"

    results = []
    for i in range(args.trials):
        page = rng.choice(PAGES)
        category = rng.choice(CATEGORIES)
        baseline_img = baselines[page]
        current_img = MUTATORS[category](baseline_img, rng)

        cv2.imwrite(str(baseline_tmp), baseline_img)
        cv2.imwrite(str(current_tmp), current_img)

        result, _, _ = compare_arrays(
            baseline=baseline_img,
            current=current_img,
            pixel_threshold=20,
            min_region_area=120,
            ignore_regions=[],
        )
        assessment = assess_result(
            result=result,
            model_path=model_path,
            baseline_image_path=baseline_tmp,
            current_image_path=current_tmp,
        )
        pred_label = assessment.label or "benign"
        expected_c = to_consolidated(category)
        pred_c = to_consolidated(pred_label)
        correct = expected_c == pred_c

        record = {
            "trial": i,
            "page": page,
            "expected": category,
            "expected_consolidated": expected_c,
            "predicted": pred_label,
            "predicted_consolidated": pred_c,
            "correct": correct,
            "mismatch_pct": result.mismatch_pct,
            "regions": len(result.regions),
            "ai_score": assessment.score,
        }
        results.append(record)
        mark = "OK " if correct else "ERR"
        print(f"[{i+1:3d}/{args.trials}] {mark} page={page:18s} expected={category:20s} predicted={pred_label:18s} mismatch={result.mismatch_pct:.3f}%")

    correct_n = sum(1 for r in results if r["correct"])
    total = len(results)
    print()
    print(f"Overall accuracy: {correct_n}/{total} = {correct_n/total:.1%}")
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

    out_file = Path(args.out) if args.out else ROOT / "scratch" / "random_mutation_eval_results.json"
    out_file.write_text(json.dumps({"seed": seed, "accuracy": correct_n / total, "results": results}, indent=2), encoding="utf-8")
    print(f"\nSaved to {out_file}")


if __name__ == "__main__":
    main()
