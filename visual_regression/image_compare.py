from __future__ import annotations

from pathlib import Path
from typing import List, Sequence, Tuple

import cv2
import numpy as np

from .models import CompareResult, DiffRegion

try:
    from skimage.metrics import structural_similarity
except Exception:  # pragma: no cover - optional at runtime
    structural_similarity = None


IgnoreRegion = Tuple[int, int, int, int]


def parse_ignore_regions(values: Sequence[str]) -> List[IgnoreRegion]:
    regions: List[IgnoreRegion] = []
    for item in values:
        parts = [part.strip() for part in item.split(",")]
        if len(parts) != 4:
            raise ValueError(f"Invalid ignore region '{item}'. Expected x,y,width,height")
        x, y, w, h = [int(part) for part in parts]
        if w <= 0 or h <= 0:
            raise ValueError(f"Invalid ignore region '{item}'. width/height must be > 0")
        regions.append((x, y, w, h))
    return regions


def _load_image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Failed to load image: {path}")
    return image


def _get_dominant_background_color(img: np.ndarray) -> tuple[int, int, int]:
    h, w = img.shape[:2]
    if h == 0 or w == 0:
        return (255, 255, 255)
    corners = [
        img[0, 0],
        img[0, w - 1],
        img[h - 1, 0],
        img[h - 1, w - 1]
    ]
    median_color = np.median(corners, axis=0).astype(np.uint8)
    return int(median_color[0]), int(median_color[1]), int(median_color[2])


def _normalize_canvas(base: np.ndarray, current: np.ndarray) -> tuple[np.ndarray, np.ndarray, tuple, tuple]:
    height = max(base.shape[0], current.shape[0])
    width = max(base.shape[1], current.shape[1])
    
    bg_base = _get_dominant_background_color(base)
    bg_current = _get_dominant_background_color(current)
    
    canvas_a = np.full((height, width, 3), bg_base, dtype=np.uint8)
    canvas_b = np.full((height, width, 3), bg_current, dtype=np.uint8)
    
    canvas_a[0 : base.shape[0], 0 : base.shape[1]] = base
    canvas_b[0 : current.shape[0], 0 : current.shape[1]] = current
    # Return the pre-computed background colours so callers can reuse them
    # without a second call to _get_dominant_background_color.
    return canvas_a, canvas_b, bg_base, bg_current



def _apply_ignore_regions(
    image: np.ndarray,
    regions: Sequence[IgnoreRegion],
    fill_color: tuple[int, int, int] = (255, 255, 255),
) -> None:
    """Fill ignore regions with a solid colour (defaults to white).

    Using each image's own dominant background colour avoids false-positive
    diffs when comparing dark-theme UIs: a white fill on a dark background
    would itself look like a change to the diff algorithm.
    """
    height, width = image.shape[:2]
    for x, y, w, h in regions:
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(width, x + w)
        y2 = min(height, y + h)
        if x2 <= x1 or y2 <= y1:
            continue
        cv2.rectangle(image, (x1, y1), (x2, y2), fill_color, thickness=-1)


def compare_arrays(
    baseline: np.ndarray,
    current: np.ndarray,
    pixel_threshold: int,
    min_region_area: int,
    ignore_regions: Sequence[IgnoreRegion],
    skip_ssim: bool = False,
) -> tuple[CompareResult, np.ndarray, np.ndarray]:
    base_canvas, current_canvas, bg_base, bg_current = _normalize_canvas(baseline, current)
    # Use each image's own background color to fill ignored regions so that
    # the fill does not itself introduce a visual difference (e.g. white on a dark UI).
    # bg_base / bg_current are returned directly by _normalize_canvas — no recompute needed.
    _apply_ignore_regions(base_canvas, ignore_regions, fill_color=bg_base)
    _apply_ignore_regions(current_canvas, ignore_regions, fill_color=bg_current)

    base_gray = cv2.cvtColor(base_canvas, cv2.COLOR_BGR2GRAY)
    current_gray = cv2.cvtColor(current_canvas, cv2.COLOR_BGR2GRAY)
    base_gray = cv2.GaussianBlur(base_gray, (3, 3), 0)
    current_gray = cv2.GaussianBlur(current_gray, (3, 3), 0)

    delta = cv2.absdiff(base_gray, current_gray)
    _, binary = cv2.threshold(delta, pixel_threshold, 255, cv2.THRESH_BINARY)

    # ── Vectorized Anti-Aliasing Suppressor ────────────────────────────────────
    # Compute neighborhood min/max using a 3x3 kernel (erosion/dilation)
    kernel_aa = np.ones((3, 3), dtype=np.uint8)
    min_b = cv2.erode(base_gray, kernel_aa)
    max_b = cv2.dilate(base_gray, kernel_aa)
    min_c = cv2.erode(current_gray, kernel_aa)
    max_c = cv2.dilate(current_gray, kernel_aa)

    # Local contrast check to ensure we only suppress pixels on high-contrast edges
    contrast_b = max_b - min_b
    contrast_c = max_c - min_c
    high_contrast = (contrast_b > 15) | (contrast_c > 15)

    # A differing pixel is classified as antialiasing if:
    # 1. It lies on a high-contrast boundary.
    # 2. Its gray value in the current image lies within the baseline neighborhood min/max.
    # 3. Its gray value in the baseline image lies within the current neighborhood min/max.
    is_aa = (
        high_contrast
        & (current_gray >= min_b)
        & (current_gray <= max_b)
        & (base_gray >= min_c)
        & (base_gray <= max_c)
    )

    aa_mask = np.zeros_like(binary)
    aa_mask[is_aa] = 255
    binary = cv2.bitwise_and(binary, cv2.bitwise_not(aa_mask))

    kernel = np.ones((3, 3), dtype=np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    binary = cv2.dilate(binary, kernel, iterations=1)

    ssim_score = None
    if structural_similarity is not None and not skip_ssim:
        score, ssim_map = structural_similarity(base_gray, current_gray, full=True)
        ssim_score = float(score)
        ssim_delta = (1.0 - ssim_map) * 255.0
        ssim_delta = np.clip(ssim_delta, 0, 255).astype(np.uint8)
        _, ssim_binary = cv2.threshold(ssim_delta, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        binary = cv2.bitwise_or(binary, ssim_binary)

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions: List[DiffRegion] = []
    for contour in contours:
        area = int(cv2.contourArea(contour))
        if area < min_region_area:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        roi = delta[y : y + h, x : x + w]
        mean_delta = float(np.mean(roi))
        regions.append(
            DiffRegion(
                x=int(x),
                y=int(y),
                width=int(w),
                height=int(h),
                area=area,
                mean_delta=round(mean_delta, 3),
            )
        )

    regions.sort(key=lambda item: item.area, reverse=True)

    diff_pixels = int(np.count_nonzero(binary))
    total_pixels = int(binary.size)
    mismatch_pct = round((diff_pixels / total_pixels) * 100.0, 4)

    # Percy-style: tint changed pixels red/magenta on current screenshot (no bounding boxes).
    overlay = current_canvas.copy().astype(np.float32)
    mask = binary > 0
    highlight_bgr = np.array([80, 80, 255], dtype=np.float32)
    overlay[mask] = overlay[mask] * 0.35 + highlight_bgr * 0.65
    overlay = np.clip(overlay, 0, 255).astype(np.uint8)

    result = CompareResult(
        baseline_size=[int(base_canvas.shape[1]), int(base_canvas.shape[0])],
        current_size=[int(current_canvas.shape[1]), int(current_canvas.shape[0])],
        diff_pixels=diff_pixels,
        total_pixels=total_pixels,
        mismatch_pct=mismatch_pct,
        ssim_score=ssim_score,
        regions=regions,
    )
    return result, overlay, binary


def compare_images(
    baseline_path: Path,
    current_path: Path,
    pixel_threshold: int,
    min_region_area: int,
    ignore_regions: Sequence[IgnoreRegion],
) -> tuple[CompareResult, np.ndarray, np.ndarray]:
    baseline = _load_image(baseline_path)
    current = _load_image(current_path)
    return compare_arrays(
        baseline=baseline,
        current=current,
        pixel_threshold=pixel_threshold,
        min_region_area=min_region_area,
        ignore_regions=ignore_regions,
    )
