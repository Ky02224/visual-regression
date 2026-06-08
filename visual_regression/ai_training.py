from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import multiprocessing

import cv2
import numpy as np

from ._json_cache import JsonCache
from .ai_datasets import load_public_dataset_manifest
from .ai_features import (
    DEFAULT_IMAGE_SIZE,
    RULE_FEATURE_NAMES,
    ensure_rgb_batch,
    feature_vector_from_result,
    normalize_batch_uint8,
    stack_feature_rows,
)
from .config import WorkspacePaths
from .image_compare import compare_arrays
from .models import AIAssessment, CompareResult

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
}
DEFAULT_CONFIDENCE_FLOOR = 0.35


def _require_torch():
    try:
        import torch
        import torch.nn as nn
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "PyTorch is required for AI training. Install it first, then rerun train-ai."
        ) from exc
    return torch, nn


def _require_torchvision():
    try:
        from torchvision.models import ResNet50_Weights, resnet50
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "torchvision is required for the ResNet50 Siamese model. Install torchvision, then rerun train-ai."
        ) from exc
    return resnet50, ResNet50_Weights


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
        image_path = baseline_dir / "baseline.png"
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
    images: List[np.ndarray] = []
    for index, item in enumerate(payload.get("images", [])):
        if max_images is not None and index >= max_images:
            break
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


def _apply_defect_variant(image: np.ndarray, seed: int, mode: str | None = None) -> tuple[np.ndarray, str]:
    rng = random.Random(seed)
    variant = image.copy()
    mode = mode or rng.choice(DEFECT_MODES)
    h, w = image.shape[:2]

    if mode == "missing_element":
        num_removals = rng.randint(1, 3)
        for _ in range(num_removals):
            rx1 = rng.randint(int(w * 0.05), int(w * 0.55))
            ry1 = rng.randint(int(h * 0.10), int(h * 0.65))
            rw = rng.randint(int(w * 0.10), int(w * 0.28))
            rh = rng.randint(int(h * 0.06), int(h * 0.16))
            rx2 = min(rx1 + rw, w - 1)
            ry2 = min(ry1 + rh, h - 1)
            cv2.rectangle(variant, (rx1, ry1), (rx2, ry2), (215, 215, 215), thickness=-1)
            cv2.rectangle(variant, (rx1, ry1), (rx2, ry2), (170, 170, 170), thickness=2)
        label = "missing-element"

    elif mode == "color_regression":
        header_h = max(int(h * 0.10), 20)
        hue_opts = [(22, 50, 200), (22, 150, 50), (150, 22, 150), (200, 80, 22), (22, 150, 200)]
        cv2.rectangle(variant, (0, 0), (w, header_h), rng.choice(hue_opts), thickness=-1)
        btn_colors = [(36, 146, 210), (210, 80, 36), (80, 210, 36), (200, 200, 22)]
        for _ in range(rng.randint(1, 3)):
            bx1 = rng.randint(int(w * 0.15), int(w * 0.55))
            by1 = rng.randint(int(h * 0.10), int(h * 0.50))
            bx2 = min(bx1 + rng.randint(int(w * 0.10), int(w * 0.18)), w - 1)
            by2 = min(by1 + rng.randint(int(h * 0.06), int(h * 0.12)), h - 1)
            cv2.rectangle(variant, (bx1, by1), (bx2, by2), rng.choice(btn_colors), thickness=-1)
        label = "color-regression"

    elif mode == "layout_shift":
        shift_pct = rng.uniform(0.06, 0.15)
        direction = rng.choice(["right", "left", "down", "up"])
        top = int(h * rng.uniform(0.10, 0.25))
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
            left = int(w * rng.uniform(0.10, 0.35))
            panel = variant[:, left:].copy()
            shifted = np.full_like(panel, 248)
            if panel.shape[0] > shift_y:
                shifted[shift_y:, :] = panel[: panel.shape[0] - shift_y, :]
            variant[:, left:] = shifted
        else:
            shift_y = int(h * shift_pct)
            left = int(w * rng.uniform(0.10, 0.35))
            panel = variant[:, left:].copy()
            shifted = np.full_like(panel, 248)
            if panel.shape[0] > shift_y:
                shifted[: panel.shape[0] - shift_y, :] = panel[shift_y:, :]
            variant[:, left:] = shifted
        label = "layout-shift"

    elif mode == "overlay_obstruction":
        overlay_type = rng.choice(["modal", "banner", "drawer"])
        if overlay_type == "modal":
            mw = int(w * rng.uniform(0.28, 0.46))
            mh = int(h * rng.uniform(0.28, 0.46))
            mx = max(0, (w - mw) // 2 + rng.randint(-60, 60))
            my = max(0, (h - mh) // 2 + rng.randint(-60, 60))
            overlay = variant.copy()
            cv2.rectangle(overlay, (0, 0), (w, h), (20, 20, 20), thickness=-1)
            variant = cv2.addWeighted(overlay, 0.45, variant, 0.55, 0)
            cv2.rectangle(variant, (mx, my), (min(mx + mw, w - 1), min(my + mh, h - 1)), (255, 255, 255), thickness=-1)
            cv2.rectangle(variant, (mx, my), (min(mx + mw, w - 1), min(my + mh, h - 1)), (190, 190, 190), thickness=2)
        elif overlay_type == "banner":
            bh = int(h * rng.uniform(0.09, 0.17))
            cv2.rectangle(variant, (0, h - bh), (w, h), (28, 28, 28), thickness=-1)
        else:
            pw = int(w * rng.uniform(0.20, 0.36))
            cv2.rectangle(variant, (w - pw, 0), (w, h), (240, 240, 240), thickness=-1)
            cv2.rectangle(variant, (w - pw, 0), (w, h), (195, 195, 195), thickness=2)
        label = "overlay-obstruction"

    elif mode == "text_truncation":
        num_rows = rng.randint(2, 6)
        start_y = int(h * rng.uniform(0.20, 0.50))
        row_h = int(h * rng.uniform(0.04, 0.075))
        x_cut = int(w * rng.uniform(0.35, 0.65))
        for idx in range(num_rows):
            top = start_y + idx * (row_h + rng.randint(2, 6))
            if top + row_h >= h:
                break
            cv2.rectangle(variant, (x_cut, top), (w - int(w * 0.03), top + row_h), (255, 255, 255), thickness=-1)
        cv2.line(variant, (x_cut, start_y), (x_cut, min(start_y + num_rows * (row_h + 4), h - 1)), (200, 200, 200), 1)
        label = "text-truncation"

    elif mode == "broken_image":
        num_slots = rng.randint(1, 3)
        for _ in range(num_slots):
            ix1 = rng.randint(int(w * 0.05), int(w * 0.55))
            iy1 = rng.randint(int(h * 0.10), int(h * 0.60))
            iw = rng.randint(int(w * 0.12), int(w * 0.30))
            ih = rng.randint(int(h * 0.08), int(h * 0.20))
            ix2 = min(ix1 + iw, w - 1)
            iy2 = min(iy1 + ih, h - 1)
            cv2.rectangle(variant, (ix1, iy1), (ix2, iy2), (205, 205, 205), thickness=-1)
            cv2.rectangle(variant, (ix1, iy1), (ix2, iy2), (140, 140, 140), thickness=2)
            cv2.line(variant, (ix1 + 4, iy1 + 4), (ix2 - 4, iy2 - 4), (160, 160, 160), 2)
            cv2.line(variant, (ix2 - 4, iy1 + 4), (ix1 + 4, iy2 - 4), (160, 160, 160), 2)
            cx, cy = (ix1 + ix2) // 2, (iy1 + iy2) // 2
            icon_size = max(8, min(iw, ih) // 5)
            cv2.rectangle(variant, (cx - icon_size, cy - icon_size), (cx + icon_size, cy + icon_size), (170, 170, 170), thickness=2)
        label = "broken-image"

    elif mode == "misaligned_fields":
        num_fields = rng.randint(3, 7)
        field_start_y = int(h * rng.uniform(0.20, 0.45))
        field_h = int(h * rng.uniform(0.04, 0.07))
        label_w = int(w * rng.uniform(0.15, 0.25))
        input_x = int(w * rng.uniform(0.30, 0.45))
        input_w = int(w * rng.uniform(0.25, 0.40))
        offset_x = rng.randint(15, 45) * rng.choice([-1, 1])
        offset_y = rng.randint(8, 25) * rng.choice([-1, 1])
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

        ref_x = input_x  
        line_top = field_start_y
        line_bottom = min(field_start_y + num_fields * gap, h - 1)
        cv2.line(variant, (ref_x, line_top), (ref_x, line_bottom), (180, 100, 100), 1)

        label = "misaligned-fields"

    elif mode == "unreadable_text":
        pattern = rng.choice(["low_contrast", "washed"])
        num_rows = rng.randint(3, 8)
        start_y = int(h * rng.uniform(0.15, 0.45))
        row_h = int(h * rng.uniform(0.025, 0.05))
        gap = row_h + rng.randint(4, 10)
        x1 = int(w * rng.uniform(0.05, 0.25))
        row_w = int(w * rng.uniform(0.40, 0.70))
        for idx in range(num_rows):
            ry = start_y + idx * gap
            if ry + row_h >= h:
                break
            rx2 = min(x1 + row_w, w - 1)
            if rx2 <= x1:
                continue
            if pattern == "low_contrast":
                fade = rng.randint(235, 250)
                cv2.rectangle(variant, (x1, ry), (rx2, ry + row_h), (fade, fade, fade), thickness=-1)
            else:
                roi = variant[ry: ry + row_h, x1: rx2].copy().astype(np.float32)
                roi = roi * 0.15 + 245 * 0.85
                variant[ry: ry + row_h, x1: rx2] = np.clip(roi, 0, 255).astype(np.uint8)
        label = "unreadable-text"

    return variant, label

@dataclass
class PairSample:
    baseline_rgb: np.ndarray
    current_rgb: np.ndarray
    rule_features: np.ndarray
    label_index: int
    label_name: str


def _extract_diff_crop(
    baseline: np.ndarray,
    current: np.ndarray,
    result: CompareResult,
    padding: int = 40,
    crop_seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Crop both images around the changed region + padding.
    If no meaningful diff (benign), fall back to a deterministic random crop."""
    h, w = baseline.shape[:2]
    if result.regions:
        x1 = max(0, min(r.x for r in result.regions) - padding)
        y1 = max(0, min(r.y for r in result.regions) - padding)
        x2 = min(w, max(r.x + r.width for r in result.regions) + padding)
        y2 = min(h, max(r.y + r.height for r in result.regions) + padding)
        if (x2 - x1) >= 64 and (y2 - y1) >= 64:
            return baseline[y1:y2, x1:x2], current[y1:y2, x1:x2]
    rng = np.random.default_rng(crop_seed)
    ch = min(h, max(256, h // 3))
    cw = min(w, max(256, w // 3))
    y0 = int(rng.integers(0, max(1, h - ch)))
    x0 = int(rng.integers(0, max(1, w - cw)))
    return baseline[y0:y0 + ch, x0:x0 + cw], current[y0:y0 + ch, x0:x0 + cw]


def _build_pair_sample(
    baseline: np.ndarray,
    current: np.ndarray,
    pixel_threshold: int,
    min_region_area: int,
    label_name: str,
    crop_seed: int = 0,
) -> PairSample:
    result, _, _ = compare_arrays(
        baseline=baseline,
        current=current,
        skip_ssim=True,
        pixel_threshold=pixel_threshold,
        min_region_area=min_region_area,
        ignore_regions=[],
    )
    baseline_crop, current_crop = _extract_diff_crop(
        baseline, current, result, padding=40, crop_seed=crop_seed
    )
    return PairSample(
        baseline_rgb=ensure_rgb_batch([baseline_crop])[0],
        current_rgb=ensure_rgb_batch([current_crop])[0],
        rule_features=feature_vector_from_result(result),
        label_index=DEFECT_LABEL_TO_INDEX[label_name] if label_name in DEFECT_LABEL_TO_INDEX else NO_DEFECT_LABEL_INDEX,
        label_name=label_name,
    )


def _load_run_pair_samples(
    paths: WorkspacePaths,
    pixel_threshold: int,
    min_region_area: int,
) -> List[PairSample]:
    samples: List[PairSample] = []
    for run_dir in sorted(paths.runs_dir.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        result_file = run_dir / "result.json"
        baseline_path = run_dir / "baseline.png"
        current_path = run_dir / "current.png"
        if not result_file.exists() or not baseline_path.exists() or not current_path.exists():
            continue

        try:
            payload = JsonCache.read(result_file)
        except Exception:
            continue

        status = str(payload.get("status") or "").upper()
        if status not in {"PASS", "FAIL"}:
            continue

        baseline_image = cv2.imread(str(baseline_path), cv2.IMREAD_COLOR)
        current_image = cv2.imread(str(current_path), cv2.IMREAD_COLOR)
        if baseline_image is None or current_image is None:
            continue

        decision_status = str(payload.get("decision", {}).get("status") or "").lower()
        if decision_status == "approved":
            label_name = BENIGN_LABEL_NAME
        elif decision_status == "rejected":
            label_name = str(payload.get("ai_assessment", {}).get("label") or "")
            if label_name not in DEFECT_LABEL_TO_INDEX:
                try:
                    from .models import CompareResult
                    res_dict = payload.get("result", {})
                    comp_res = CompareResult(
                        baseline_size=res_dict.get("baseline_size", [baseline_image.shape[1], baseline_image.shape[0]]),
                        current_size=res_dict.get("current_size", [current_image.shape[1], current_image.shape[0]]),
                        diff_pixels=res_dict.get("diff_pixels", 0),
                        total_pixels=res_dict.get("total_pixels", 1),
                        mismatch_pct=res_dict.get("mismatch_pct", 0.0),
                        ssim_score=res_dict.get("ssim_score"),
                        regions=[],
                    )
                    label_name = _heuristic_defect_label(comp_res, baseline_image, current_image) or DEFECT_LABELS[0]
                except Exception:
                    label_name = DEFECT_LABELS[0]
        else:
            if status == "PASS":
                label_name = BENIGN_LABEL_NAME
            else:
                label_name = str(payload.get("ai_assessment", {}).get("label") or "")
                if label_name not in DEFECT_LABEL_TO_INDEX:
                    continue

        samples.append(
            _build_pair_sample(
                baseline=baseline_image,
                current=current_image,
                pixel_threshold=pixel_threshold,
                min_region_area=min_region_area,
                label_name=label_name,
            )
        )
    return samples


def _collate_numpy(batch: list) -> tuple:
    baselines = np.stack([b[0] for b in batch])
    currents = np.stack([b[1] for b in batch])
    rules = np.stack([b[2] for b in batch])
    labels = np.array([b[3] for b in batch], dtype=np.int64)
    return baselines, currents, rules, labels


class StreamingSyntheticDataset:
    """Generates pair-samples on-the-fly — only source images live in RAM."""
    _MAX_SRC_PX = 1200  # resize source images to this max dim to save RAM (~15 GB for 5000 imgs)

    def __init__(
        self,
        base_images: List[np.ndarray],
        samples_per_image: int,
        pixel_threshold: int,
        min_region_area: int,
        seed_offset: int = 0,
    ) -> None:
        self.base_images: List[np.ndarray] = []
        for img in base_images:
            h, w = img.shape[:2]
            if max(h, w) > self._MAX_SRC_PX:
                scale = self._MAX_SRC_PX / max(h, w)
                img_resized = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
                self.base_images.append(img_resized)
            else:
                self.base_images.append(img.copy())
        
        self.samples_per_image = samples_per_image
        self.pixel_threshold = pixel_threshold
        self.min_region_area = min_region_area
        self.seed_offset = seed_offset
        # Pre-compute mode pool once — avoids rebuilding on every __getitem__
        self.modes_pool: List[tuple] = []
        for bi in range(3):
            self.modes_pool.append((BENIGN_LABEL_NAME, bi))
        for dm in DEFECT_MODES:
            for ri in range(DEFECT_MODE_WEIGHTS.get(dm, 1)):
                self.modes_pool.append((dm, 100 + ri))
        self.variants_per_iter = len(self.modes_pool)
        self.total_variants_per_image = self.samples_per_image * self.variants_per_iter
        self._run_pairs: List[PairSample] = []

    def add_run_pairs(self, pairs: "List[PairSample]") -> None:
        self._run_pairs.extend(pairs)

    def __len__(self) -> int:
        return (len(self.base_images) * self.total_variants_per_image) + len(self._run_pairs)

    def __getitem__(self, idx: int) -> tuple:
        synthetic_total = len(self.base_images) * self.total_variants_per_image
        if idx >= synthetic_total:
            s = self._run_pairs[idx - synthetic_total]
            return s.baseline_rgb, s.current_rgb, s.rule_features, np.int64(s.label_index)
        img_idx = idx // self.total_variants_per_image
        intra = idx % self.total_variants_per_image
        iter_idx = intra // self.variants_per_iter
        mode_pool_idx = intra % self.variants_per_iter
        mode, mode_seed_offset = self.modes_pool[mode_pool_idx]
        seed = (self.seed_offset + img_idx) * 10_000_000 + iter_idx * 1000 + mode_seed_offset
        base = self.base_images[img_idx]
        if mode == BENIGN_LABEL_NAME:
            variant = _apply_benign_variant(base, seed)
            label_name = BENIGN_LABEL_NAME
        else:
            variant, label_name = _apply_defect_variant(base, seed, mode=mode)
        sample = _build_pair_sample(
            baseline=base,
            current=variant,
            pixel_threshold=self.pixel_threshold,
            min_region_area=self.min_region_area,
            label_name=label_name,
            crop_seed=seed,
        )
        return sample.baseline_rgb, sample.current_rgb, sample.rule_features, np.int64(sample.label_index)

    def class_label_array(self) -> np.ndarray:
        """Compute class counts in O(modes_pool) — no large array built."""
        counts = np.zeros(len(DEFECT_LABELS), dtype=np.int64)
        per_img = len(self.base_images) * self.samples_per_image
        for mode, _ in self.modes_pool:
            if mode == BENIGN_LABEL_NAME or mode not in DEFECT_LABEL_TO_INDEX:
                continue
            label_idx = DEFECT_LABEL_TO_INDEX[mode]
            counts[label_idx] += per_img
        for s in self._run_pairs:
            counts[s.label_index] += 1
        return counts


def _process_one_image(args: tuple) -> "List[PairSample]":
    """Top-level worker for multiprocessing pool — generates all samples for one base image."""
    base, img_idx, samples_per_image, pixel_threshold, min_region_area = args
    result: List[PairSample] = []
    seed_base = img_idx * 10_000_000
    for iter_idx in range(samples_per_image):
        sample_seed = seed_base + iter_idx * 1000
        for benign_idx in range(3):
            good_variant = _apply_benign_variant(base, sample_seed + benign_idx)
            result.append(
                _build_pair_sample(
                    baseline=base,
                    current=good_variant,
                    pixel_threshold=pixel_threshold,
                    min_region_area=min_region_area,
                    label_name=BENIGN_LABEL_NAME,
                    crop_seed=sample_seed + benign_idx,
                )
            )
        for defect_mode in DEFECT_MODES:
            repeat = DEFECT_MODE_WEIGHTS.get(defect_mode, 1)
            for repeat_index in range(repeat):
                bad_variant, defect_label = _apply_defect_variant(
                    base,
                    sample_seed + 100 + repeat_index,
                    mode=defect_mode,
                )
                result.append(
                    _build_pair_sample(
                        baseline=base,
                        current=bad_variant,
                        pixel_threshold=pixel_threshold,
                        min_region_area=min_region_area,
                        label_name=defect_label,
                        crop_seed=sample_seed + 100 + repeat_index,
                    )
                )
    return result


def build_synthetic_dataset(
    paths: WorkspacePaths,
    samples_per_image: int,
    pixel_threshold: int,
    min_region_area: int,
    dataset_manifest_path: Path | None = None,
    max_public_images: int | None = None,
    images: List[np.ndarray] | None = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    samples: List[PairSample] = []
    if images is not None:
        base_images: List[np.ndarray] = list(images)
    else:
        base_images = _load_base_images(paths)
        public_images = _load_public_dataset_images(dataset_manifest_path, max_images=max_public_images)
        if public_images:
            base_images.extend(public_images)

    num_workers = min(4, max(1, multiprocessing.cpu_count() - 1))
    batch_size_img = 200  # process 200 images per pool batch to avoid OOM
    total = len(base_images)
    print(f"  Generating samples: {total} images × {samples_per_image} iters  workers={num_workers}  img_batch={batch_size_img}", flush=True)
    for batch_start in range(0, total, batch_size_img):
        batch_imgs = base_images[batch_start : batch_start + batch_size_img]
        args_list = [
            (img, batch_start + idx, samples_per_image, pixel_threshold, min_region_area)
            for idx, img in enumerate(batch_imgs)
        ]
        with multiprocessing.Pool(num_workers) as pool:
            batches = pool.map(_process_one_image, args_list)
        for b in batches:
            samples.extend(b)
        print(f"  [{batch_start + len(batch_imgs)}/{total}] {len(samples)} samples so far", flush=True)

    if images is None:
        samples.extend(_load_run_pair_samples(paths, pixel_threshold=pixel_threshold, min_region_area=min_region_area))

    if not samples:
        raise ValueError("No training samples could be created")

    baseline_images = np.stack([sample.baseline_rgb for sample in samples], axis=0)
    current_images = np.stack([sample.current_rgb for sample in samples], axis=0)
    rule_features = stack_feature_rows([sample.rule_features for sample in samples])
    labels = np.asarray([sample.label_index for sample in samples], dtype=np.int64)
    return baseline_images, current_images, rule_features, labels


def _compute_multiclass_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    class_names: Sequence[str],
) -> Dict[str, object]:
    num_classes = len(class_names)
    confusion = np.zeros((num_classes, num_classes), dtype=np.int64)
    for truth, pred in zip(y_true.astype(int), y_pred.astype(int)):
        confusion[truth, pred] += 1

    per_class: List[Dict[str, object]] = []
    for index, name in enumerate(class_names):
        tp = int(confusion[index, index])
        fp = int(confusion[:, index].sum() - tp)
        fn = int(confusion[index, :].sum() - tp)
        precision = float(tp / max(tp + fp, 1))
        recall = float(tp / max(tp + fn, 1))
        per_class.append(
            {
                "label": name,
                "precision": round(precision, 6),
                "recall": round(recall, 6),
                "support": int(confusion[index, :].sum()),
            }
        )

    accuracy = float((y_true == y_pred).mean()) if len(y_true) else 1.0
    return {
        "accuracy": round(accuracy, 6),
        "confusion_matrix": confusion.tolist(),
        "per_class": per_class,
    }


def _build_resnet50_backbone(pretrained: bool):
    _, nn = _require_torch()
    resnet50, ResNet50_Weights = _require_torchvision()

    weights = None
    weights_source = "random-init"
    if pretrained:
        try:
            weights = ResNet50_Weights.DEFAULT
            weights_source = "imagenet-default"
        except Exception:
            weights = None

    try:
        model = resnet50(weights=weights)
    except Exception:
        model = resnet50(weights=None)
        weights_source = "random-init"

    feature_dim = int(model.fc.in_features)
    backbone = nn.Sequential(*list(model.children())[:-1])
    freeze_backbone = weights_source == "imagenet-default"
    for name, parameter in backbone.named_parameters():
        if "7." in name or "layer4" in name:
            parameter.requires_grad = True
        else:
            parameter.requires_grad = not freeze_backbone
            
    any_backbone_trainable = any(p.requires_grad for p in backbone.parameters())
    freeze_backbone = not any_backbone_trainable
    if freeze_backbone:
        backbone.eval()
    return backbone, feature_dim, weights_source, freeze_backbone


class LegacyRuleMLP:  # pragma: no cover - only used for older checkpoints
    def __init__(self, torch_module, nn_module, checkpoint: Dict[str, object]):
        self.torch = torch_module
        self.model = nn_module.Sequential(
            nn_module.Linear(int(checkpoint["input_dim"]), 32),
            nn_module.ReLU(),
            nn_module.Dropout(0.15),
            nn_module.Linear(32, 16),
            nn_module.ReLU(),
            nn_module.Linear(16, 1),
        )
        self.model.load_state_dict(checkpoint["state_dict"])
        self.model.eval()
        self.threshold = float(checkpoint.get("threshold", 0.5))

    def score(self, result: CompareResult) -> float:
        vector = self.torch.tensor(feature_vector_from_result(result), dtype=self.torch.float32).unsqueeze(0)
        with self.torch.no_grad():
            return float(self.torch.sigmoid(self.model(vector)).item())


class SiameseFusionHead:  
    def __init__(self, nn_module, embedding_dim: int, rule_dim: int, output_dim: int):
        self.model = nn_module.Sequential(
            nn_module.Linear((embedding_dim * 3) + rule_dim, 1024),
            nn_module.BatchNorm1d(1024),       
            nn_module.ReLU(),
            nn_module.Dropout(0.15),         
            nn_module.Linear(1024, 256),
            nn_module.BatchNorm1d(256),      
            nn_module.ReLU(),
            nn_module.Dropout(0.08),           
            nn_module.Linear(256, output_dim),
        )

    def __call__(self, left_embedding, right_embedding, rule_features):
        distance = (left_embedding - right_embedding).abs()
        combined = self._concat(left_embedding, right_embedding, distance, rule_features)
        return self.model(combined)

    @staticmethod
    def _concat(left_embedding, right_embedding, distance, rule_features):
        import torch

        return torch.cat([left_embedding, right_embedding, distance, rule_features], dim=1)


class FocalLoss:
    def __init__(self, torch_module, weight=None, gamma=2.0, ignore_index=-1):
        self.torch = torch_module
        self.weight = weight
        self.gamma = gamma
        self.ignore_index = ignore_index

    def __call__(self, input_logits, target_labels):
        import torch.nn.functional as F
        
        # Mask out ignore index
        mask = target_labels != self.ignore_index
        input_logits = input_logits[mask]
        target_labels = target_labels[mask]
        
        if target_labels.numel() == 0:
            return self.torch.tensor(0.0, device=input_logits.device, requires_grad=True)

        ce_loss = F.cross_entropy(input_logits, target_labels, reduction='none', weight=self.weight)
        pt = self.torch.exp(-ce_loss)
        focal_loss = ((1.0 - pt) ** self.gamma) * ce_loss
        return focal_loss.mean()


def _heuristic_defect_label(result: CompareResult, baseline_image: np.ndarray, current_image: np.ndarray) -> str:
    region_count = len(result.regions)
    if result.mismatch_pct < 0.2 and region_count <= 1:
        return ""
    if not result.regions:
        return ""

    total_pixels = float(max(result.total_pixels, 1))
    largest = max(result.regions, key=lambda region: region.area)
    largest_ratio = float(largest.area) / total_pixels
    thin_bands = [region for region in result.regions if region.height <= 36 and region.width >= 140]
    aligned_bands = [region for region in thin_bands if region.x >= int(baseline_image.shape[1] * 0.45)]
    if len(aligned_bands) >= 3:
        return "text-truncation"

    if 3 <= region_count <= 10:
        sorted_by_y = sorted(result.regions, key=lambda r: r.y)
        areas = [r.area for r in sorted_by_y]
        area_cv = float(np.std(areas) / max(np.mean(areas), 1e-6)) 
        y_gaps = [sorted_by_y[i+1].y - sorted_by_y[i].y for i in range(len(sorted_by_y) - 1)]
        gap_cv = float(np.std(y_gaps) / max(np.mean(y_gaps), 1e-6)) if y_gaps else 1.0
      
        if area_cv < 0.5 and gap_cv < 0.4 and largest_ratio <= 0.06:
            return "misaligned-fields"


    y_end = min(largest.y + largest.height, baseline_image.shape[0])
    x_end = min(largest.x + largest.width, baseline_image.shape[1])
    baseline_crop = baseline_image[largest.y:y_end, largest.x:x_end]
    current_crop = current_image[largest.y:y_end, largest.x:x_end]
    if baseline_crop.size and current_crop.size:
        color_delta = float(np.mean(np.abs(baseline_crop.astype(np.float32) - current_crop.astype(np.float32))))
        current_brightness = float(np.mean(current_crop))
                
        bright_thin_bands = [r for r in result.regions if r.height <= 30 and r.width >= 80]
        if (
            len(bright_thin_bands) >= 3
            and current_brightness >= 220.0
            and color_delta < 15.0
        ):
            return "unreadable-text"

        if largest.y < 140 and largest.width >= int(baseline_image.shape[1] * 0.55) and color_delta >= 18.0:
            return "color-regression"
        if color_delta >= 22.0 and largest_ratio <= 0.04 and region_count <= 4:
            return "color-regression"
        if current_brightness <= 60.0 and largest_ratio >= 0.02:
            return "overlay-obstruction"

    if region_count >= 6 or largest_ratio >= 0.05:
        return "layout-shift"
    return "missing-element"


def _apply_hard_feature_veto(
    label: str,
    result: CompareResult,
    baseline_image: np.ndarray,
    current_image: np.ndarray,
) -> str:
    """Override AI label when feature evidence directly contradicts the prediction."""
    if not result.regions:
        return ""
    total_pixels = float(max(result.total_pixels, 1))
    largest = max(result.regions, key=lambda r: r.area)
    largest_ratio = float(largest.area) / total_pixels
    region_count = len(result.regions)
    y_end = min(largest.y + largest.height, baseline_image.shape[0])
    x_end = min(largest.x + largest.width, baseline_image.shape[1])
    baseline_crop = baseline_image[largest.y:y_end, largest.x:x_end]
    current_crop = current_image[largest.y:y_end, largest.x:x_end]
    color_delta = 0.0
    current_brightness = 128.0
    if baseline_crop.size and current_crop.size:
        color_delta = float(np.mean(np.abs(baseline_crop.astype(np.float32) - current_crop.astype(np.float32))))
        current_brightness = float(np.mean(current_crop))

    if label == "misaligned-fields":
        if not (3 <= region_count <= 10):
            return _heuristic_defect_label(result, baseline_image, current_image)
        sorted_by_y = sorted(result.regions, key=lambda r: r.y)
        areas = [r.area for r in sorted_by_y]
        area_cv = float(np.std(areas) / max(np.mean(areas), 1e-6))
        if area_cv >= 0.5:
            return _heuristic_defect_label(result, baseline_image, current_image)
  
    if label == "unreadable-text":
        bright_thin_bands = [r for r in result.regions if r.height <= 30 and r.width >= 80]
        if not (len(bright_thin_bands) >= 3 and current_brightness >= 220.0 and color_delta < 15.0):
            return _heuristic_defect_label(result, baseline_image, current_image)

    if label == "color-regression" and color_delta < 8.0:
        return _heuristic_defect_label(result, baseline_image, current_image)
    if label == "overlay-obstruction" and current_brightness > 170.0:
        return _heuristic_defect_label(result, baseline_image, current_image)
    if label == "missing-element" and largest_ratio >= 0.20:
        return "layout-shift"
    if label == "layout-shift" and region_count >= 8 and largest_ratio <= 0.03:
        return "text-truncation"
    if label in {"broken-image", "missing-element"} and color_delta >= 22.0 and largest_ratio <= 0.04:
        return "color-regression"
    return label


def _encode_batch(torch_module, backbone, batch_rgb: np.ndarray, device: str, track_grad: bool = False):
    tensor = torch_module.tensor(normalize_batch_uint8(batch_rgb), dtype=torch_module.float32, device=device)
    if not track_grad:
        with torch_module.no_grad():
            embedding = backbone(tensor).flatten(1)
        return embedding
    else:
        embedding = backbone(tensor).flatten(1)
    return embedding


def _precompute_embeddings(torch_module, backbone, images: np.ndarray, device: str, batch_size: int = 32) -> "torch.Tensor":
    """Run ResNet50 once over all images and return cached embeddings tensor."""
    all_embeddings = []
    backbone.eval()
    with torch_module.no_grad():
        for start in range(0, len(images), batch_size):
            batch = images[start : start + batch_size]
            tensor = torch_module.tensor(normalize_batch_uint8(batch), dtype=torch_module.float32, device=device)
            emb = backbone(tensor).flatten(1)
            all_embeddings.append(emb)
    return torch_module.cat(all_embeddings, dim=0)


def train_model(
    paths: WorkspacePaths,
    model_path: Path | None = None,
    epochs: int = 30,
    batch_size: int = 32,
    learning_rate: float = 1e-3,
    samples_per_image: int = 16,
    pixel_threshold: int = 20,
    min_region_area: int = 120,
    pretrained_backbone: bool = True,
    dataset_manifest_path: Path | None = None,
    max_public_images: int | None = None,
) -> Dict[str, object]:
    torch, nn = _require_torch()
    paths.ensure()
    model_path = model_path or (paths.models_dir / "visual_ai.pt")

    # Set low process priority class to prevent computer lag
    try:
        import psutil
        p = psutil.Process()
        # 0x00000040 is BELOW_NORMAL_PRIORITY_CLASS
        p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except Exception:
        pass

    # Constrain CPU threads to avoid CPU starvation
    try:
        torch.set_num_threads(2)
        torch.set_num_interop_threads(1)
    except Exception:
        pass

    # Physical 80/20 split on SOURCE IMAGES before generating samples (prevents data leakage)
    _src_max_px = StreamingSyntheticDataset._MAX_SRC_PX
    all_src_images: List[np.ndarray] = _load_base_images(paths, max_px=_src_max_px)
    public_imgs = _load_public_dataset_images(dataset_manifest_path, max_images=max_public_images, max_px=_src_max_px)
    if public_imgs:
        all_src_images.extend(public_imgs)
    src_rng = np.random.default_rng(42)
    src_idx = src_rng.permutation(len(all_src_images))
    train_cut = max(1, int(len(src_idx) * 0.8))
    train_imgs = [all_src_images[i] for i in src_idx[:train_cut]]
    val_imgs = [all_src_images[i] for i in src_idx[train_cut:]]
    print(f"  Image split: {len(train_imgs)} train / {len(val_imgs)} val (physical isolation)", flush=True)

    # --- Streaming datasets (samples generated on-the-fly, no OOM) ---
    train_dataset = StreamingSyntheticDataset(
        base_images=train_imgs,
        samples_per_image=samples_per_image,
        pixel_threshold=pixel_threshold,
        min_region_area=min_region_area,
        seed_offset=0,
    )
    run_smp = _load_run_pair_samples(paths, pixel_threshold=pixel_threshold, min_region_area=min_region_area)
    if run_smp:
        train_dataset.add_run_pairs(run_smp)
    val_dataset = StreamingSyntheticDataset(
        base_images=val_imgs if val_imgs else [],
        samples_per_image=max(2, samples_per_image // 4),
        pixel_threshold=pixel_threshold,
        min_region_area=min_region_area,
        seed_offset=999_999,
    )
    # Free original full-res images — datasets already hold resized copies
    n_public_imgs = len(public_imgs)
    del all_src_images, public_imgs, train_imgs, val_imgs
    import gc; gc.collect()
    print(f"  Streaming dataset: {len(train_dataset):,} train  {len(val_dataset):,} val samples", flush=True)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    num_gpus = torch.cuda.device_count() if device == "cuda" else 0
    print(f"  Device: {device.upper()}  GPUs: {num_gpus}", flush=True)

    backbone, embedding_dim, weights_source, freeze_backbone = _build_resnet50_backbone(pretrained=pretrained_backbone)
    backbone = backbone.to(device)
    backbone.eval()

    head = SiameseFusionHead(
        nn,
        embedding_dim=embedding_dim,
        rule_dim=len(RULE_FEATURE_NAMES),
        output_dim=len(DEFECT_LABELS),
    ).model.to(device)

    if num_gpus > 1:
        print(f"  DataParallel: splitting across {num_gpus} GPUs", flush=True)
        head = nn.DataParallel(head)
        backbone = nn.DataParallel(backbone)

    # Set up differential learning rates
    train_params = []
    # Classifier head gets the main learning rate
    head_trainable = [p for p in head.parameters() if p.requires_grad]
    if head_trainable:
        train_params.append({
            "params": head_trainable,
            "lr": learning_rate
        })
    # Unfrozen backbone layers get a 10x smaller learning rate to preserve features
    if not freeze_backbone:
        backbone.train()
        backbone_trainable = [p for p in backbone.parameters() if p.requires_grad]
        if backbone_trainable:
            train_params.append({
                "params": backbone_trainable,
                "lr": learning_rate * 0.1
            })

    # Class weights for Focal Loss
    class_counts = train_dataset.class_label_array().astype(np.float32)
    class_counts[class_counts == 0.0] = 1.0
    class_weights = class_counts.sum() / class_counts
    class_weights = class_weights / class_weights.mean()
    
    # Initialize Focal Loss to handle severe class imbalance
    criterion = FocalLoss(
        torch_module=torch,
        weight=torch.tensor(class_weights, dtype=torch.float32, device=device),
        gamma=2.0,
        ignore_index=NO_DEFECT_LABEL_INDEX,
    )

    from torch.utils.data import DataLoader
    dl_workers = min(1, max(0, multiprocessing.cpu_count() - 1))
    train_loader = DataLoader(
        train_dataset, batch_size=batch_size, shuffle=True,
        num_workers=dl_workers, collate_fn=_collate_numpy,
        pin_memory=(device == "cuda"), persistent_workers=(dl_workers > 0),
    )
    val_loader = DataLoader(
        val_dataset, batch_size=batch_size, shuffle=False,
        num_workers=dl_workers, collate_fn=_collate_numpy,
        pin_memory=(device == "cuda"), persistent_workers=(dl_workers > 0),
    ) if len(val_dataset) > 0 else None

    # Initialize optimizer with grouped learning rates
    optimizer = torch.optim.Adam(train_params)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)

    # Checkpoint resume: load previous state if exists
    ckpt_path = model_path.with_suffix(".ckpt.pt")
    start_epoch = 1
    recent_losses: List[float] = []
    if ckpt_path.exists():
        print(f"  Resuming from checkpoint: {ckpt_path}", flush=True)
        ckpt = torch.load(ckpt_path, map_location=device)
        (head.module if isinstance(head, nn.DataParallel) else head).load_state_dict(ckpt["head_state_dict"])
        if not freeze_backbone:
            (backbone.module if isinstance(backbone, nn.DataParallel) else backbone).load_state_dict(ckpt["backbone_state_dict"])
        optimizer.load_state_dict(ckpt["optimizer_state_dict"])
        scheduler.load_state_dict(ckpt["scheduler_state_dict"])
        start_epoch = ckpt["epoch"] + 1
        recent_losses = ckpt.get("recent_losses", [])
        print(f"  Resumed at epoch {start_epoch}/{epochs}", flush=True)
    elif model_path.exists():
        print(f"  Fine-tuning from saved model: {model_path}", flush=True)
        saved = torch.load(model_path, map_location=device)
        head_module = head.module if isinstance(head, nn.DataParallel) else head
        if "classifier_state_dict" in saved:
            head_module.load_state_dict(saved["classifier_state_dict"])
        elif "head_state_dict" in saved:
            head_module.load_state_dict(saved["head_state_dict"])
        if not freeze_backbone and saved.get("backbone_state_dict"):
            backbone_module = backbone.module if isinstance(backbone, nn.DataParallel) else backbone
            backbone_module.load_state_dict(saved["backbone_state_dict"])
        print("  Loaded model weights (optimizer reset — fine-tune mode)", flush=True)

    try:
        from tqdm import tqdm as _tqdm
    except ImportError:
        _tqdm = None

    for epoch_num in range(start_epoch, epochs + 1):
        head.train()
        if not freeze_backbone:
            backbone.train()
        epoch_loss = 0.0
        num_batches = 0
        loader_iter = _tqdm(train_loader, desc=f"Epoch {epoch_num}/{epochs}", unit="batch", leave=False) if _tqdm else train_loader
        for bl_batch, cur_batch, rule_np, lbl_np in loader_iter:
            with torch.no_grad() if freeze_backbone else torch.enable_grad():  # type: ignore[attr-defined]
                left_emb = backbone(torch.tensor(normalize_batch_uint8(bl_batch), dtype=torch.float32, device=device)).flatten(1)
                right_emb = backbone(torch.tensor(normalize_batch_uint8(cur_batch), dtype=torch.float32, device=device)).flatten(1)
            if freeze_backbone:
                left_emb = left_emb.detach()
                right_emb = right_emb.detach()
            rule_t = torch.tensor(rule_np, dtype=torch.float32, device=device)
            combined = torch.cat([left_emb, right_emb, (left_emb - right_emb).abs(), rule_t], dim=1)
            logits = head(combined)
            target = torch.tensor(lbl_np, dtype=torch.long, device=device)
            optimizer.zero_grad()
            loss = criterion(logits, target)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()
            num_batches += 1
        scheduler.step()
        avg_loss = epoch_loss / max(num_batches, 1)
        recent_losses.append(avg_loss)
        if len(recent_losses) > 5:
            recent_losses.pop(0)
        print(f"  Epoch {epoch_num}/{epochs}  loss={avg_loss:.4f}  lr={scheduler.get_last_lr()[0]:.2e}", flush=True)
        if epoch_num == 5 and len(recent_losses) == 5 and (recent_losses[0] - recent_losses[-1]) < 0.005:
            print("  [WARNING] Loss barely improved in first 5 epochs. Consider lowering --learning-rate to 3e-4.", flush=True)
        # Save checkpoint after every epoch
        torch.save({
            "epoch": epoch_num,
            "head_state_dict": (head.module if isinstance(head, nn.DataParallel) else head).state_dict(),
            "backbone_state_dict": (backbone.module if isinstance(backbone, nn.DataParallel) else backbone).state_dict(),
            "optimizer_state_dict": optimizer.state_dict(),
            "scheduler_state_dict": scheduler.state_dict(),
            "recent_losses": recent_losses,
        }, ckpt_path)
        print(f"  [ckpt] Saved → {ckpt_path.name}", flush=True)
        kaggle_out = Path("/kaggle/working/visual_ai.ckpt.pt")
        if Path("/kaggle/working").exists():
            import shutil as _shutil
            _shutil.copy(str(ckpt_path), str(kaggle_out))
            print(f"  [ckpt] Copied to {kaggle_out}", flush=True)

    head.eval()
    backbone.eval()
    all_val_preds: List[int] = []
    all_val_targets: List[int] = []
    if val_loader is not None:
        with torch.no_grad():
            for bl_batch, cur_batch, rule_np, lbl_np in val_loader:
                left_emb = backbone(torch.tensor(normalize_batch_uint8(bl_batch), dtype=torch.float32, device=device)).flatten(1)
                right_emb = backbone(torch.tensor(normalize_batch_uint8(cur_batch), dtype=torch.float32, device=device)).flatten(1)
                rule_t = torch.tensor(rule_np, dtype=torch.float32, device=device)
                combined = torch.cat([left_emb, right_emb, (left_emb - right_emb).abs(), rule_t], dim=1)
                preds = torch.argmax(head(combined), dim=1).cpu().numpy()
                all_val_preds.extend(preds.tolist())
                all_val_targets.extend(lbl_np.tolist())
    if all_val_targets:
        accuracy = float(np.mean(np.array(all_val_preds) == np.array(all_val_targets)))
        metrics = _compute_multiclass_metrics(
            y_true=np.array(all_val_targets, dtype=np.int64),
            y_pred=np.array(all_val_preds, dtype=np.int64),
            class_names=DEFECT_LABELS,
        )
    else:
        accuracy = 1.0
        metrics = _compute_multiclass_metrics(
            y_true=np.asarray([0], dtype=np.int64),
            y_pred=np.asarray([0], dtype=np.int64),
            class_names=DEFECT_LABELS,
        )

    checkpoint = {
        "model_type": "resnet50-siamese-rule-fusion-multiclass",
        "architecture": "ResNet50 Siamese + OpenCV/SSIM Fusion",
        "weights_source": weights_source,
        "backbone": "resnet50",
        "pretrained_backbone": pretrained_backbone,
        "freeze_backbone": freeze_backbone,
        "image_size": DEFAULT_IMAGE_SIZE,
        "rule_feature_names": RULE_FEATURE_NAMES,
        "threshold": DEFAULT_CONFIDENCE_FLOOR,
        "class_names": DEFECT_LABELS,
        "embedding_dim": embedding_dim,
        "backbone_state_dict": (backbone.module if isinstance(backbone, nn.DataParallel) else backbone).state_dict(),
        "classifier_state_dict": (head.module if isinstance(head, nn.DataParallel) else head).state_dict(),
        "accuracy": accuracy,
        "samples": len(train_dataset),
        "evaluation": metrics,
    }
    torch.save(checkpoint, model_path)

    metadata = {
        "model_path": str(model_path),
        "model_type": checkpoint["model_type"],
        "architecture": checkpoint["architecture"],
        "weights_source": weights_source,
        "freeze_backbone": freeze_backbone,
        "class_names": DEFECT_LABELS,
        "feature_names": RULE_FEATURE_NAMES,
        "accuracy": accuracy,
        "samples": len(train_dataset),
        "epochs": epochs,
        "image_size": DEFAULT_IMAGE_SIZE,
        "backbone": "resnet50",
        "dataset_manifest": str(dataset_manifest_path) if dataset_manifest_path else None,
        "public_images_used": n_public_imgs,
        "evaluation": metrics,
    }
    metadata_path = model_path.with_suffix(".json")
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    eval_path = paths.reports_dir / f"ai-eval-{model_path.stem}.json"
    eval_payload = {
        "model_path": str(model_path),
        "class_names": DEFECT_LABELS,
        "evaluation": metrics,
        "samples": len(train_dataset),
        "dataset_manifest": str(dataset_manifest_path) if dataset_manifest_path else None,
    }
    eval_path.write_text(json.dumps(eval_payload, indent=2), encoding="utf-8")
    return metadata


_cached_loaded_model = None
_cached_model_path = None
_cached_model_mtime = None


def _load_legacy_or_hybrid_model(model_path: Path):
    global _cached_loaded_model, _cached_model_path, _cached_model_mtime
    import os
    mtime = None
    try:
        mtime = os.path.getmtime(model_path)
        if _cached_loaded_model is not None and _cached_model_path == model_path and _cached_model_mtime == mtime:
            return _cached_loaded_model
    except Exception:
        pass

    torch, nn = _require_torch()
    checkpoint = torch.load(model_path, map_location="cpu")
    model_type = str(checkpoint.get("model_type") or "legacy-rule-mlp")

    if model_type == "legacy-rule-mlp" or "classifier_state_dict" not in checkpoint:
        loaded_dict = {
            "type": "legacy",
            "runner": LegacyRuleMLP(torch, nn, checkpoint),
            "threshold": float(checkpoint.get("threshold", 0.5)),
        }
        if mtime is not None:
            _cached_loaded_model = loaded_dict
            _cached_model_path = model_path
            _cached_model_mtime = mtime
        return loaded_dict

    backbone, embedding_dim, _, _ = _build_resnet50_backbone(pretrained=bool(checkpoint.get("pretrained_backbone", True)))
    backbone = backbone.to("cpu")
    if checkpoint.get("backbone_state_dict"):
        backbone.load_state_dict(checkpoint["backbone_state_dict"])
    backbone.eval()

    class_names = list(checkpoint.get("class_names", []))
    output_dim = len(class_names) if class_names else 1
    head = SiameseFusionHead(
        nn,
        embedding_dim=embedding_dim,
        rule_dim=len(checkpoint.get("rule_feature_names", RULE_FEATURE_NAMES)),
        output_dim=output_dim,
    ).model
    head.load_state_dict(checkpoint["classifier_state_dict"])
    head.eval()
    
    loaded_dict = {
        "type": "hybrid-multiclass" if class_names else "hybrid-binary",
        "torch": torch,
        "backbone": backbone,
        "head": head,
        "threshold": float(checkpoint.get("threshold", 0.5)),
        "image_size": int(checkpoint.get("image_size", DEFAULT_IMAGE_SIZE)),
        "model_type": model_type,
        "class_names": class_names,
    }
    if mtime is not None:
        _cached_loaded_model = loaded_dict
        _cached_model_path = model_path
        _cached_model_mtime = mtime
    return loaded_dict




def _is_micro_rendering_noise(result: CompareResult) -> bool:
    """Ignore single-pixel / glyph anti-aliasing noise (e.g. select arrow, icon edge)."""
    if not result.regions:
        return result.mismatch_pct < 0.05
    if len(result.regions) > 2:
        return False
    if result.mismatch_pct >= 0.08:
        return False
    largest = max(region.area for region in result.regions)
    if largest >= 800:
        return False
    if result.mismatch_pct < 0.05 and largest < 500:
        return True
    if result.mismatch_pct < 0.04 and largest < 1200:
        return True
    return False


def _should_suppress_ai_label(result: CompareResult, label: str, score: float, threshold: float) -> bool:
    if not label or label in {"insignificant-change", "meaningful-change", BENIGN_LABEL_NAME}:
        return True
    if _is_micro_rendering_noise(result):
        return True
    if result.mismatch_pct < 0.2 and not result.regions:
        return True
    if score < min(threshold, DEFAULT_CONFIDENCE_FLOOR):
        return True
    return False


def _meaningful_change_from_label(label: str) -> bool:
    normalized = str(label or "").strip()
    if not normalized:
        return False
    if normalized in {"insignificant-change", BENIGN_LABEL_NAME}:
        return False
    return True


def _build_ai_assessment(score: float, label: str, threshold: float, model_name: str) -> AIAssessment:
    return AIAssessment(
        score=round(score, 6),
        label=label,
        threshold=threshold,
        model_name=model_name,
        meaningful_change=_meaningful_change_from_label(label),
    )


def assess_result(
    result: CompareResult,
    model_path: Path,
    baseline_image_path: Path | None = None,
    current_image_path: Path | None = None,
) -> AIAssessment:
    loaded = _load_legacy_or_hybrid_model(model_path)

    if loaded["type"] == "legacy":
        score = float(loaded["runner"].score(result))
        threshold = float(loaded["threshold"])
        label = "meaningful-change" if score >= threshold else ""
        if _should_suppress_ai_label(result, label, score, threshold):
            label = ""
        return _build_ai_assessment(score, label, threshold, model_path.name)

    if not baseline_image_path or not current_image_path:
        raise ValueError("Hybrid AI assessment requires baseline and current image paths.")

    baseline_image = cv2.imread(str(baseline_image_path), cv2.IMREAD_COLOR)
    current_image = cv2.imread(str(current_image_path), cv2.IMREAD_COLOR)
    if baseline_image is None or current_image is None:
        raise ValueError("Failed to read baseline/current images for hybrid AI assessment.")

    torch = loaded["torch"]
    img_size = int(loaded["image_size"])
    baseline_crop, current_crop = _extract_diff_crop(baseline_image, current_image, result, padding=40)
    baseline_batch = ensure_rgb_batch([baseline_crop], image_size=img_size)
    current_batch = ensure_rgb_batch([current_crop], image_size=img_size)
    left_embedding = _encode_batch(torch, loaded["backbone"], baseline_batch, "cpu")
    right_embedding = _encode_batch(torch, loaded["backbone"], current_batch, "cpu")
    rule_vector = torch.tensor(feature_vector_from_result(result), dtype=torch.float32).unsqueeze(0)

    with torch.no_grad():
        combined = torch.cat([left_embedding, right_embedding, (left_embedding - right_embedding).abs(), rule_vector], dim=1)
        logits = loaded["head"](combined)
        if loaded["type"] == "hybrid-binary":
            score = float(torch.sigmoid(logits).item())
            threshold = float(loaded["threshold"])
            label = "meaningful-change" if score >= threshold else ""
        else:
            probabilities = torch.softmax(logits, dim=1).squeeze(0)
            top_index = int(torch.argmax(probabilities).item())
            score = float(probabilities[top_index].item())
            threshold = float(loaded["threshold"])
            class_names = list(loaded["class_names"])
            label = class_names[top_index] if top_index < len(class_names) else ""
            if label == "insignificant-change":
                label = ""
            elif score < threshold:
                label = _heuristic_defect_label(result, baseline_image, current_image)
            else:
                label = _apply_hard_feature_veto(label, result, baseline_image, current_image)
    if _should_suppress_ai_label(result, label, score, threshold):
        label = ""
    return _build_ai_assessment(score, label, threshold, model_path.name)


def evaluate_model_on_runs(paths: WorkspacePaths, model_path: Path) -> Dict[str, object]:
    samples = _load_run_pair_samples(paths, pixel_threshold=20, min_region_area=120)
    if not samples:
        return {
            "model_path": str(model_path),
            "samples": 0,
            "class_names": DEFECT_LABELS,
            "evaluation": _compute_multiclass_metrics(
                y_true=np.asarray([0], dtype=np.int64),
                y_pred=np.asarray([0], dtype=np.int64),
                class_names=DEFECT_LABELS,
            ),
        }

    predictions: List[int] = []
    labels: List[int] = []
    baseline_temp = paths.root / "tmp-ai-eval-baseline.png"
    current_temp = paths.root / "tmp-ai-eval-current.png"
    for sample in samples:
        result, _, _ = compare_arrays(
            baseline=cv2.cvtColor(sample.baseline_rgb, cv2.COLOR_RGB2BGR),
            current=cv2.cvtColor(sample.current_rgb, cv2.COLOR_RGB2BGR),
            pixel_threshold=20,
            min_region_area=120,
            ignore_regions=[],
        )
        _write_temp_eval_image(sample.baseline_rgb, baseline_temp)
        _write_temp_eval_image(sample.current_rgb, current_temp)
        assessment = assess_result(
            result=result,
            model_path=model_path,
            baseline_image_path=baseline_temp,
            current_image_path=current_temp,
        )
        if sample.label_index < 0:
            continue
        label_name = assessment.label if assessment.label in DEFECT_LABEL_TO_INDEX else DEFECT_LABELS[0]
        predictions.append(DEFECT_LABEL_TO_INDEX[label_name])
        labels.append(sample.label_index)
    baseline_temp.unlink(missing_ok=True)
    current_temp.unlink(missing_ok=True)

    metrics = _compute_multiclass_metrics(
        y_true=np.asarray(labels, dtype=np.int64),
        y_pred=np.asarray(predictions, dtype=np.int64),
        class_names=DEFECT_LABELS,
    )
    payload = {
        "model_path": str(model_path),
        "samples": len(samples),
        "class_names": DEFECT_LABELS,
        "evaluation": metrics,
    }
    output_path = paths.reports_dir / f"ai-run-eval-{model_path.stem}.json"
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _write_temp_eval_image(rgb_image: np.ndarray, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(target), cv2.cvtColor(rgb_image, cv2.COLOR_RGB2BGR))