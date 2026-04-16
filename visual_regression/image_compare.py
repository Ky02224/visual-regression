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


def _normalize_canvas(base: np.ndarray, current: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    height = max(base.shape[0], current.shape[0])
    width = max(base.shape[1], current.shape[1])
    canvas_a = np.full((height, width, 3), 255, dtype=np.uint8)
    canvas_b = np.full((height, width, 3), 255, dtype=np.uint8)
    canvas_a[0 : base.shape[0], 0 : base.shape[1]] = base
    canvas_b[0 : current.shape[0], 0 : current.shape[1]] = current
    return canvas_a, canvas_b


def _apply_ignore_regions(image: np.ndarray, regions: Sequence[IgnoreRegion]) -> None:
    height, width = image.shape[:2]
    for x, y, w, h in regions:
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(width, x + w)
        y2 = min(height, y + h)
        if x2 <= x1 or y2 <= y1:
            continue
        cv2.rectangle(image, (x1, y1), (x2, y2), (255, 255, 255), thickness=-1)


def compare_arrays(
    baseline: np.ndarray,
    current: np.ndarray,
    pixel_threshold: int,
    min_region_area: int,
    ignore_regions: Sequence[IgnoreRegion],
) -> tuple[CompareResult, np.ndarray, np.ndarray]:
    base_canvas, current_canvas = _normalize_canvas(baseline, current)
    _apply_ignore_regions(base_canvas, ignore_regions)
    _apply_ignore_regions(current_canvas, ignore_regions)

    base_gray = cv2.cvtColor(base_canvas, cv2.COLOR_BGR2GRAY)
    current_gray = cv2.cvtColor(current_canvas, cv2.COLOR_BGR2GRAY)

    delta = cv2.absdiff(base_gray, current_gray)
    _, binary = cv2.threshold(delta, pixel_threshold, 255, cv2.THRESH_BINARY)
    kernel = np.ones((3, 3), dtype=np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    binary = cv2.dilate(binary, kernel, iterations=1)

    ssim_score = None
    if structural_similarity is not None:
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

    overlay = current_canvas.copy()
    heat = cv2.applyColorMap(delta, cv2.COLORMAP_JET)
    overlay = cv2.addWeighted(overlay, 0.72, heat, 0.28, 0)
    for idx, region in enumerate(regions, start=1):
        p1 = (region.x, region.y)
        p2 = (region.x + region.width, region.y + region.height)
        cv2.rectangle(overlay, p1, p2, (0, 0, 255), thickness=2)
        cv2.putText(
            overlay,
            str(idx),
            (region.x, max(18, region.y - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 255),
            2,
            lineType=cv2.LINE_AA,
        )

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
