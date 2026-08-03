from __future__ import annotations

import cv2
import numpy as np
import random
from pathlib import Path
from typing import List

from .ai_datasets import load_public_dataset_manifest
from .config import WorkspacePaths, resolve_image_path

NO_DEFECT_LABEL_INDEX = -1
BENIGN_LABEL_NAME = "__benign__"

DEFECT_LABELS = [
    "missing-element",
    "layout-shift",
    "color-regression",
    "text-truncation",
    "overlay-obstruction",
    "broken-image",
    "misaligned-fields",
    "unreadable-text",
    "z-index-issue",
    "font-change",
]
DEFECT_LABEL_TO_INDEX = {label: idx for idx, label in enumerate(DEFECT_LABELS)}
DEFECT_MODES = [
    "missing_element",
    "layout_shift",
    "color_regression",
    "text_truncation",
    "overlay_obstruction",
    "broken_image",
    "misaligned_fields",
    "unreadable_text",
    "z_index_issue",
    "font_change",
]
DEFECT_MODE_WEIGHTS = {
    "missing_element": 2,
    "layout_shift": 2,
    "color_regression": 3,
    "text_truncation": 3,
    "overlay_obstruction": 2,
    "broken_image": 2,
    "misaligned_fields": 2,
    "unreadable_text": 2,
    "z_index_issue": 2,
    "font_change": 2,
}
DEFECT_MODE_TO_LABEL = {
    "missing_element": "missing-element",
    "layout_shift": "layout-shift",
    "color_regression": "color-regression",
    "text_truncation": "text-truncation",
    "overlay_obstruction": "overlay-obstruction",
    "broken_image": "broken-image",
    "misaligned_fields": "misaligned-fields",
    "unreadable_text": "unreadable-text",
    "z_index_issue": "z-index-issue",
    "font_change": "font-change",
}


def _draw_base_ui(seed: int, width: int = 1440, height: int = 900) -> np.ndarray:
    rng = random.Random(seed)
    image = np.full((height, width, 3), 248, dtype=np.uint8)

    cv2.rectangle(image, (0, 0), (width, 88), (28, 62, 106), thickness=-1)
    cv2.rectangle(image, (40, 116), (360, 820), (255, 255, 255), thickness=-1)
    cv2.rectangle(image, (396, 116), (width - 40, 820), (255, 255, 255), thickness=-1)

    for idx in range(5):
        y = 150 + idx * 108
        cv2.rectangle(image, (72, y), (330, y + 62), (236, 240, 245), thickness=-1)

    card_colors = [(240, 247, 255), (241, 255, 246), (255, 247, 237), (245, 243, 255)]
    for idx in range(4):
        x = 440 + idx * 230
        cv2.rectangle(image, (x, 160), (x + 180, 270), card_colors[idx], thickness=-1)

    for idx in range(6):
        top = 328 + idx * 72
        cv2.rectangle(image, (440, top), (width - 90, top + 44), (243, 244, 246), thickness=-1)

    cv2.putText(image, "Visual Regression Demo", (56, 58), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    cv2.putText(image, f"seed-{seed}", (width - 190, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (220, 235, 255), 2)

    for _ in range(8):
        x1 = rng.randint(440, width - 160)
        y1 = rng.randint(340, 760)
        x2 = min(width - 80, x1 + rng.randint(50, 120))
        y2 = min(810, y1 + rng.randint(10, 22))
        cv2.rectangle(image, (x1, y1), (x2, y2), (223, 228, 235), thickness=-1)
    return image


def _resize_to_max(image: np.ndarray, max_px: int) -> np.ndarray:
    h, w = image.shape[:2]
    if max(h, w) > max_px:
        scale = max_px / max(h, w)
        return cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return image


def _load_base_images(paths: WorkspacePaths, max_px: int = 0) -> List[np.ndarray]:
    bases: List[np.ndarray] = []
    for baseline_dir in paths.baselines_dir.iterdir():
        image_path = resolve_image_path(baseline_dir, "baseline")
        if not image_path.exists():
            continue
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is not None:
            bases.append(_resize_to_max(image, max_px) if max_px else image)
    if bases:
        return bases
    return [_draw_base_ui(seed) for seed in range(6)]


def _load_public_dataset_images(manifest_path: Path | None, max_images: int | None = None, max_px: int = 0) -> List[np.ndarray]:
    if not manifest_path:
        return []
    if not manifest_path.exists():
        raise FileNotFoundError(f"Dataset manifest not found: {manifest_path}")

    payload = load_public_dataset_manifest(manifest_path)
    
    # Group image items by source
    by_source: dict[str, list] = {}
    for item in payload.get("images", []):
        src = item.get("source", "unknown")
        if src not in by_source:
            by_source[src] = []
        by_source[src].append(item)
        
    # Cap items per source to balance loading across all sources
    items_to_load = []
    if max_images is not None and by_source:
        num_sources = len(by_source)
        limit_per_source = max(1, max_images // num_sources)
        for _src, src_items in by_source.items():
            items_to_load.extend(src_items[:limit_per_source])
    else:
        for _src, src_items in by_source.items():
            items_to_load.extend(src_items)

    images: List[np.ndarray] = []
    for item in items_to_load:
        image_path = Path(str(item.get("path", "")))
        if not image_path.exists():
            continue
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            continue
        if min(image.shape[:2]) < 64:
            continue
        images.append(_resize_to_max(image, max_px) if max_px else image)
    return images


def _apply_benign_variant(image: np.ndarray, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    variant = image.copy().astype(np.float32)
    brightness = rng.uniform(-12.0, 12.0)
    contrast = rng.uniform(0.88, 1.12)
    variant = variant * contrast + brightness
    noise = rng.normal(0.0, 2.5, size=variant.shape)
    variant += noise
    variant = np.clip(variant, 0, 255).astype(np.uint8)
    if seed % 3 == 0:
        variant = cv2.GaussianBlur(variant, (3, 3), 0)
    if seed % 5 == 0:
        variant = cv2.GaussianBlur(variant, (5, 5), 0)
    if seed % 7 == 0:
        hsv = cv2.cvtColor(variant, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * rng.uniform(0.85, 1.15), 0, 255)
        variant = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    h, w = variant.shape[:2]
    if seed % 11 == 0:
        shift_x = int(rng.integers(-5, 6))
        shift_y = int(rng.integers(-5, 6))
        matrix = np.float32([[1, 0, shift_x], [0, 1, shift_y]])
        variant = cv2.warpAffine(variant, matrix, (w, h), borderMode=cv2.BORDER_REPLICATE)
    if seed % 13 == 0:
        scale = float(rng.uniform(0.99, 1.01))
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        resized = cv2.resize(variant, (new_w, new_h), interpolation=cv2.INTER_AREA)
        canvas = np.full_like(variant, 248)
        y0 = max(0, (h - new_h) // 2)
        x0 = max(0, (w - new_w) // 2)
        canvas[y0 : y0 + new_h, x0 : x0 + new_w] = resized[: min(new_h, h - y0), : min(new_w, w - x0)]
        variant = canvas
    if seed % 17 == 0:
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), int(rng.integers(72, 96))]
        ok, encoded = cv2.imencode(".jpg", variant, encode_param)
        if ok:
            variant = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    return variant



def _sample_bg_color(img, x, y):
    h, w = img.shape[:2]
    samples = []
    for dy in [-2, 0, 2]:
        for dx in [-2, 0, 2]:
            px = max(0, min(x + dx, w - 1))
            py = max(0, min(y + dy, h - 1))
            samples.append(img[py, px])
    median_color = np.median(samples, axis=0)
    return tuple(int(c) for c in median_color)


def _apply_defect_variant(image, seed, mode=None):
    # Use np.random.default_rng for consistency with _apply_benign_variant.
    # Conversion: randint(a,b) inclusive -> integers(a, b+1); choice(seq) -> seq[integers(len)]
    rng = np.random.default_rng(seed)
    variant = image.copy()
    mode = mode or DEFECT_MODES[int(rng.integers(len(DEFECT_MODES)))]
    h, w = image.shape[:2]

    if mode == "missing_element":
        # Realistic: element gone, leaves white empty gap
        # Real webpages: when an element disappears, the DOM collapses and shows
        # the page background (white) in that region. Baseline has content;
        # current shows a blank white placeholder -> very strong visual signal.
        num_removals = int(rng.integers(1, 4))
        for _ in range(num_removals):
            rx1 = int(rng.integers(int(w * 0.05), int(w * 0.55) + 1))
            ry1 = int(rng.integers(int(h * 0.10), int(h * 0.65) + 1))
            rw = int(rng.integers(int(w * 0.12), int(w * 0.30) + 1))
            rh = int(rng.integers(int(h * 0.07), int(h * 0.18) + 1))
            rx2 = min(rx1 + rw, w - 1)
            ry2 = min(ry1 + rh, h - 1)
            # Fill with sampled background color (element completely gone).
            # No placeholder border: a removed element leaves plain background,
            # not a dashed outline — a drawn border would be a synthetic-only
            # tell the model could shortcut on instead of learning the real
            # "content used to be here" pattern.
            bg_color = _sample_bg_color(image, rx1, ry1)
            cv2.rectangle(variant, (rx1, ry1), (rx2, ry2), bg_color, thickness=-1)
        label = "missing-element"

    elif mode == "color_regression":
        # Unchanged (already works well at 100%)
        header_h = max(int(h * 0.10), 20)
        hue_opts = [(22, 50, 200), (22, 150, 50), (150, 22, 150), (200, 80, 22), (22, 150, 200)]
        cv2.rectangle(variant, (0, 0), (w, header_h), hue_opts[int(rng.integers(len(hue_opts)))], thickness=-1)
        btn_colors = [(36, 146, 210), (210, 80, 36), (80, 210, 36), (200, 200, 22)]
        for _ in range(int(rng.integers(1, 4))):
            bx1 = int(rng.integers(int(w * 0.15), int(w * 0.55) + 1))
            by1 = int(rng.integers(int(h * 0.10), int(h * 0.50) + 1))
            bx2 = min(bx1 + int(rng.integers(int(w * 0.10), int(w * 0.18) + 1)), w - 1)
            by2 = min(by1 + int(rng.integers(int(h * 0.06), int(h * 0.12) + 1)), h - 1)
            cv2.rectangle(variant, (bx1, by1), (bx2, by2), btn_colors[int(rng.integers(len(btn_colors)))], thickness=-1)
        label = "color-regression"

    elif mode == "layout_shift":
        # Realistic: aggressive shift (9-18%), no break-line marker — a real
        # reflow bug never draws a grey seam at the shift boundary, so leaving
        # one in training data taught the model to key off that instead of
        # the actual displaced-content pattern.
        shift_pct = float(rng.uniform(0.09, 0.18))
        directions = ["right", "left", "down", "up"]
        direction = directions[int(rng.integers(len(directions)))]
        top = int(h * float(rng.uniform(0.10, 0.25)))
        if direction == "right":
            shift_x = int(w * shift_pct)
            panel = variant[top:, :].copy()
            shifted = np.full_like(panel, 248)
            if panel.shape[1] > shift_x:
                shifted[:, shift_x:] = panel[:, : panel.shape[1] - shift_x]
            variant[top:, :] = shifted
        elif direction == "left":
            shift_x = int(w * shift_pct)
            panel = variant[top:, :].copy()
            shifted = np.full_like(panel, 248)
            if panel.shape[1] > shift_x:
                shifted[:, : panel.shape[1] - shift_x] = panel[:, shift_x:]
            variant[top:, :] = shifted
        elif direction == "down":
            shift_y = int(h * shift_pct)
            left = int(w * float(rng.uniform(0.10, 0.35)))
            panel = variant[:, left:].copy()
            shifted = np.full_like(panel, 248)
            if panel.shape[0] > shift_y:
                shifted[shift_y:, :] = panel[: panel.shape[0] - shift_y, :]
            variant[:, left:] = shifted
        else:
            shift_y = int(h * shift_pct)
            left = int(w * float(rng.uniform(0.10, 0.35)))
            panel = variant[:, left:].copy()
            shifted = np.full_like(panel, 248)
            if panel.shape[0] > shift_y:
                shifted[: panel.shape[0] - shift_y, :] = panel[shift_y:, :]
            variant[:, left:] = shifted
            cv2.line(variant, (left, h - shift_y), (w - 1, h - shift_y), (160, 160, 160), 2)
        label = "layout-shift"

    elif mode == "overlay_obstruction":
        # Unchanged (works well)
        overlay_types = ["modal", "banner", "drawer"]
        overlay_type = overlay_types[int(rng.integers(len(overlay_types)))]
        if overlay_type == "modal":
            mw = int(w * float(rng.uniform(0.28, 0.46)))
            mh = int(h * float(rng.uniform(0.28, 0.46)))
            mx = max(0, (w - mw) // 2 + int(rng.integers(-60, 61)))
            my = max(0, (h - mh) // 2 + int(rng.integers(-60, 61)))
            overlay = variant.copy()
            cv2.rectangle(overlay, (0, 0), (w, h), (20, 20, 20), thickness=-1)
            variant = cv2.addWeighted(overlay, 0.45, variant, 0.55, 0)
            cv2.rectangle(variant, (mx, my), (min(mx + mw, w - 1), min(my + mh, h - 1)), (255, 255, 255), thickness=-1)
            cv2.rectangle(variant, (mx, my), (min(mx + mw, w - 1), min(my + mh, h - 1)), (190, 190, 190), thickness=2)
        elif overlay_type == "banner":
            bh = int(h * float(rng.uniform(0.09, 0.17)))
            cv2.rectangle(variant, (0, h - bh), (w, h), (28, 28, 28), thickness=-1)
        else:
            pw = int(w * float(rng.uniform(0.20, 0.36)))
            cv2.rectangle(variant, (w - pw, 0), (w, h), (240, 240, 240), thickness=-1)
            cv2.rectangle(variant, (w - pw, 0), (w, h), (195, 195, 195), thickness=2)
        label = "overlay-obstruction"

    elif mode == "text_truncation":
        # Realistic: text cut off by overflow:hidden — no clip-line marker,
        # since real CSS truncation doesn't draw a seam at the cut boundary.
        num_rows = int(rng.integers(2, 7))
        start_y = int(h * float(rng.uniform(0.20, 0.50)))
        row_h = int(h * float(rng.uniform(0.04, 0.075)))
        x_cut = int(w * float(rng.uniform(0.35, 0.65)))
        for idx in range(num_rows):
            top = start_y + idx * (row_h + int(rng.integers(2, 7)))
            if top + row_h >= h:
                break
            cv2.rectangle(variant, (x_cut, top), (w - int(w * 0.03), top + row_h), (255, 255, 255), thickness=-1)
        label = "text-truncation"

    elif mode == "broken_image":
        # Realistic: broken image placeholder with X icon and red-tinted border
        # Enforces minimum 80x60px so it is always clearly visible to the AI.
        num_slots = int(rng.integers(1, 4))
        for _ in range(num_slots):
            ix1 = int(rng.integers(int(w * 0.05), int(w * 0.55) + 1))
            iy1 = int(rng.integers(int(h * 0.10), int(h * 0.60) + 1))
            iw = max(80, int(rng.integers(int(w * 0.12), int(w * 0.30) + 1)))
            ih = max(60, int(rng.integers(int(h * 0.08), int(h * 0.20) + 1)))
            ix2 = min(ix1 + iw, w - 1)
            iy2 = min(iy1 + ih, h - 1)
            cv2.rectangle(variant, (ix1, iy1), (ix2, iy2), (205, 205, 205), thickness=-1)
            cv2.rectangle(variant, (ix1, iy1), (ix2, iy2), (110, 110, 190), thickness=3)
            cv2.line(variant, (ix1 + 6, iy1 + 6), (ix2 - 6, iy2 - 6), (130, 130, 130), 2)
            cv2.line(variant, (ix2 - 6, iy1 + 6), (ix1 + 6, iy2 - 6), (130, 130, 130), 2)
            cx, cy = (ix1 + ix2) // 2, (iy1 + iy2) // 2
            icon_size = max(12, min(iw, ih) // 5)
            cv2.rectangle(variant,
                          (cx - icon_size, cy - icon_size),
                          (cx + icon_size, cy + icon_size),
                          (150, 150, 150), thickness=2)
        label = "broken-image"

    elif mode == "misaligned_fields":
        # Unchanged (works adequately)
        num_fields = int(rng.integers(3, 8))
        field_start_y = int(h * float(rng.uniform(0.20, 0.45)))
        field_h = int(h * float(rng.uniform(0.04, 0.07)))
        label_w = int(w * float(rng.uniform(0.15, 0.25)))
        input_x = int(w * float(rng.uniform(0.30, 0.45)))
        input_w = int(w * float(rng.uniform(0.25, 0.40)))
        offset_x = int(rng.integers(15, 46)) * [-1, 1][int(rng.integers(2))]
        offset_y = int(rng.integers(8, 26)) * [-1, 1][int(rng.integers(2))]
        gap = int(h * 0.065)
        label_x = int(w * 0.05)
        for idx in range(num_fields):
            fy = field_start_y + idx * gap
            if fy + field_h >= h:
                break
            cv2.rectangle(variant, (label_x, fy), (label_x + label_w, fy + field_h - 4), (200, 200, 200), thickness=-1)
            new_x = max(0, min(input_x + offset_x, w - input_w - 1))
            new_y = max(0, min(fy + offset_y, h - field_h - 1))
            cv2.rectangle(variant, (new_x, new_y), (new_x + input_w, new_y + field_h - 4), (230, 230, 230), thickness=-1)
            cv2.rectangle(variant, (new_x, new_y), (new_x + input_w, new_y + field_h - 4), (160, 160, 160), thickness=1)
        label = "misaligned-fields"

    elif mode == "unreadable_text":
        # Unchanged (works adequately)
        text_patterns = ["low_contrast", "washed"]
        pattern = text_patterns[int(rng.integers(len(text_patterns)))]
        num_rows = int(rng.integers(3, 9))
        start_y = int(h * float(rng.uniform(0.15, 0.45)))
        row_h = int(h * float(rng.uniform(0.025, 0.05)))
        gap = row_h + int(rng.integers(4, 11))
        x1 = int(w * float(rng.uniform(0.05, 0.25)))
        row_w = int(w * float(rng.uniform(0.40, 0.70)))
        for idx in range(num_rows):
            ry = start_y + idx * gap
            if ry + row_h >= h:
                break
            rx2 = min(x1 + row_w, w - 1)
            if rx2 <= x1:
                continue
            if pattern == "low_contrast":
                fade = int(rng.integers(235, 251))
                cv2.rectangle(variant, (x1, ry), (rx2, ry + row_h), (fade, fade, fade), thickness=-1)
            else:
                roi = variant[ry: ry + row_h, x1: rx2].copy().astype(np.float32)
                roi = roi * 0.15 + 245 * 0.85
                variant[ry: ry + row_h, x1: rx2] = np.clip(roi, 0, 255).astype(np.uint8)
        label = "unreadable-text"

    elif mode == "z_index_issue":
        # Unchanged (works adequately)
        bx1 = int(rng.integers(int(w * 0.15), int(w * 0.45) + 1))
        by1 = int(rng.integers(int(h * 0.15), int(h * 0.45) + 1))
        bw = int(rng.integers(int(w * 0.20), int(w * 0.35) + 1))
        bh = int(rng.integers(int(h * 0.15), int(h * 0.30) + 1))
        bx2 = min(bx1 + bw, w - 1)
        by2 = min(by1 + bh, h - 1)
        # A blank white panel covering existing content — no debug text: a
        # real z-index/stacking bug never labels itself, so burning "Z-INDEX
        # CORRUPT" into the pixels was pure answer leakage the model could
        # OCR-shortcut on instead of learning the actual occlusion pattern.
        cv2.rectangle(variant, (bx1, by1), (bx2, by2), (255, 255, 255), thickness=-1)
        cv2.rectangle(variant, (bx1, by1), (bx2, by2), (40, 40, 40), thickness=2)
        label = "z-index-issue"

    elif mode == "font_change":
        # Realistic: simulate CSS font-size increase by upscaling the content region
        # Real CSS font-size change makes text rows taller; content below shifts down.
        # We take the actual page content in that area and vertically scale it up
        # (1.4x to 1.9x), giving the visual appearance of larger rendered text.
        start_y = int(h * float(rng.uniform(0.15, 0.50)))
        region_h = int(h * float(rng.uniform(0.10, 0.22)))
        region_x1 = int(w * float(rng.uniform(0.03, 0.15)))
        region_x2 = int(w * float(rng.uniform(0.60, 0.92)))
        region_y1 = start_y
        region_y2 = min(start_y + region_h, h - 1)

        if region_y2 > region_y1 + 10 and region_x2 > region_x1 + 20:
            region = variant[region_y1:region_y2, region_x1:region_x2].copy()
            reg_h, reg_w = region.shape[:2]
            scale = float(rng.uniform(1.40, 1.90))
            new_h = min(int(reg_h * scale), h - region_y1)
            # Upscale region vertically (bigger font -> taller rows)
            scaled = cv2.resize(region, (reg_w, new_h), interpolation=cv2.INTER_LINEAR)
            paste_h = min(scaled.shape[0], h - region_y1)
            variant[region_y1:region_y1 + paste_h, region_x1:region_x2] = scaled[:paste_h, :]
            # Fill the overflow gap with page background (content pushed down)
            fill_y1 = region_y1 + paste_h
            fill_y2 = min(region_y2 + int(reg_h * (scale - 1.0)), h - 1)
            if fill_y2 > fill_y1:
                bg_color = _sample_bg_color(image, region_x1, region_y1)
                cv2.rectangle(variant, (region_x1, fill_y1), (region_x2, fill_y2), bg_color, thickness=-1)
        label = "font-change"

    return variant, label

