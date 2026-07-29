from __future__ import annotations

import logging
import os
import threading
import atexit
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Sequence, Tuple, Union, Any

import cv2
import numpy as np

from .models import CompareResult, DiffRegion

try:
    from skimage.metrics import structural_similarity
except Exception:  # pragma: no cover - optional at runtime
    structural_similarity = None

logger = logging.getLogger(__name__)

IgnoreRegion = Tuple[int, int, int, int]

_PERSISTENT_PROCESS_POOL = None
_PERSISTENT_POOL_LOCK = threading.Lock()

def get_persistent_process_pool(max_workers: int | None = None) -> Any:
    global _PERSISTENT_PROCESS_POOL
    if _PERSISTENT_PROCESS_POOL is None:
        with _PERSISTENT_POOL_LOCK:
            if _PERSISTENT_PROCESS_POOL is None:
                from concurrent.futures import ProcessPoolExecutor
                effective_workers = max_workers or min(os.cpu_count() or 1, 8)
                _PERSISTENT_PROCESS_POOL = ProcessPoolExecutor(max_workers=effective_workers)
    return _PERSISTENT_PROCESS_POOL

def _shutdown_persistent_pool():
    global _PERSISTENT_PROCESS_POOL
    if _PERSISTENT_PROCESS_POOL is not None:
        try:
            _PERSISTENT_PROCESS_POOL.shutdown(wait=False)
        except Exception:
            pass
        _PERSISTENT_PROCESS_POOL = None

atexit.register(_shutdown_persistent_pool)


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
    if not path.exists():
        raise FileNotFoundError(f"Image file not found: {path}")
    if path.stat().st_size == 0:
        raise ValueError(f"Image file is empty: {path}")
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Failed to load image (corrupted or invalid format): {path}")
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


def _merge_nearby_regions(regions: List[DiffRegion], merge_gap: int = 20) -> List[DiffRegion]:
    """Merge regions that are close to each other within merge_gap pixels in both X and Y."""
    if len(regions) <= 1:
        return regions
    merged_any = True
    current_regions = list(regions)
    while merged_any:
        merged_any = False
        new_regions = []
        used = set()
        for i in range(len(current_regions)):
            if i in used:
                continue
            r1 = current_regions[i]
            merged_r = r1
            for j in range(i + 1, len(current_regions)):
                if j in used:
                    continue
                r2 = current_regions[j]
                dist_x = max(0, max(r2.x, merged_r.x) - min(r2.x + r2.width, merged_r.x + merged_r.width))
                dist_y = max(0, max(r2.y, merged_r.y) - min(r2.y + r2.height, merged_r.y + merged_r.height))
                if dist_x <= merge_gap and dist_y <= merge_gap:
                    x_min = min(merged_r.x, r2.x)
                    y_min = min(merged_r.y, r2.y)
                    x_max = max(merged_r.x + merged_r.width, r2.x + r2.width)
                    y_max = max(merged_r.y + merged_r.height, r2.y + r2.height)
                    merged_r = DiffRegion(
                        x=int(x_min),
                        y=int(y_min),
                        width=int(x_max - x_min),
                        height=int(y_max - y_min),
                        area=int(merged_r.area + r2.area),
                        mean_delta=round((merged_r.mean_delta * merged_r.area + r2.mean_delta * r2.area) / max(merged_r.area + r2.area, 1), 3)
                    )
                    used.add(j)
                    merged_any = True
            new_regions.append(merged_r)
        current_regions = new_regions
    return current_regions


def compare_arrays(
    baseline: np.ndarray,
    current: np.ndarray,
    pixel_threshold: int,
    min_region_area: int,
    ignore_regions: Sequence[IgnoreRegion],
    skip_ssim: bool = False,
    blur_radius: int = 3,
    highlight_style: str = "magenta",
) -> tuple[CompareResult, np.ndarray, np.ndarray]:
    base_canvas, current_canvas, bg_base, bg_current = _normalize_canvas(baseline, current)
    # Fill both canvases with the SAME color (baseline's) so an ignored
    # region is byte-identical in both images and can never itself register
    # a diff. Filling each canvas with its own dominant color (bg_base vs.
    # bg_current independently) defeats the purpose whenever the two differ
    # even slightly — which happens often, since it's a per-image heuristic —
    # turning the "ignored" rectangle into two different solid colors that
    # register as a spurious diff region of their own.
    _apply_ignore_regions(base_canvas, ignore_regions, fill_color=bg_base)
    _apply_ignore_regions(current_canvas, ignore_regions, fill_color=bg_base)

    base_gray = cv2.cvtColor(base_canvas, cv2.COLOR_BGR2GRAY)
    current_gray = cv2.cvtColor(current_canvas, cv2.COLOR_BGR2GRAY)
    base_color = base_canvas
    current_color = current_canvas

    if blur_radius > 0:
        ksize = blur_radius if blur_radius % 2 != 0 else blur_radius + 1
        base_gray = cv2.GaussianBlur(base_gray, (ksize, ksize), 0)
        current_gray = cv2.GaussianBlur(current_gray, (ksize, ksize), 0)
        base_color = cv2.GaussianBlur(base_canvas, (ksize, ksize), 0)
        current_color = cv2.GaussianBlur(current_canvas, (ksize, ksize), 0)

    # Grayscale diff alone is blind to pure hue shifts of similar luminance
    # (e.g. a blue→purple theme regression can land under the pixel threshold),
    # so fold in the strongest per-channel color difference as well.
    delta_gray = cv2.absdiff(base_gray, current_gray)
    delta_color = cv2.absdiff(base_color, current_color).max(axis=2)
    delta = np.maximum(delta_gray, delta_color)
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

    # Sticky/Fixed Top Header Shadow Noise Suppressor (Ignore 1-2px shadow shifts on sticky top headers).
    # Scoped to a thin strip (box-shadow blur is only a few px) and a low delta ceiling close to the
    # anti-aliasing noise floor, so it doesn't swallow real header color/layout regressions — the whole
    # 100px band at delta<28 previously erased genuine changes before the color-regression veto logic saw them.
    h_canvas = base_canvas.shape[0]
    sticky_header_mask = np.zeros_like(binary)
    sticky_header_mask[:min(12, h_canvas), :] = 1
    sticky_shadow_noise = (sticky_header_mask == 1) & (delta < 12)
    binary[sticky_shadow_noise] = 0

    aa_mask = np.zeros_like(binary)
    aa_mask[is_aa] = 255
    binary = cv2.bitwise_and(binary, cv2.bitwise_not(aa_mask))

    kernel = np.ones((3, 3), dtype=np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    binary = cv2.dilate(binary, kernel, iterations=1)

    init_diff_pixels = int(np.count_nonzero(binary))
    init_total_pixels = int(binary.size)
    init_mismatch_pct = (init_diff_pixels / max(init_total_pixels, 1)) * 100.0

    ssim_score = None
    if init_diff_pixels == 0:
        ssim_score = 1.0
    elif init_mismatch_pct < 0.05:
        ssim_score = 1.0
    elif structural_similarity is not None and not skip_ssim:
        # Find candidate bounding boxes to compute local SSIM
        # We dilate the current binary mask to group close changes
        dilate_kernel = np.ones((15, 15), dtype=np.uint8)
        dilated_binary = cv2.dilate(binary, dilate_kernel, iterations=1)
        temp_contours, _ = cv2.findContours(dilated_binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        bboxes = []
        for c in temp_contours:
            bx, by, bw, bh = cv2.boundingRect(c)
            if bw >= 2 and bh >= 2:
                bboxes.append((bx, by, bw, bh))
                
        if not bboxes:
            ssim_score = 1.0
        else:
            pad = 16
            h_img, w_img = base_gray.shape[:2]
            weighted_sum = 0.0
            total_weight = 0.0
            
            for bx, by, bw, bh in bboxes:
                x1 = max(0, bx - pad)
                y1 = max(0, by - pad)
                x2 = min(w_img, bx + bw + pad)
                y2 = min(h_img, by + bh + pad)
                
                # Check crop size is valid
                if (x2 - x1) >= 2 and (y2 - y1) >= 2:
                    base_crop = base_gray[y1:y2, x1:x2]
                    current_crop = current_gray[y1:y2, x1:x2]
                    
                    win_size = min(7, base_crop.shape[0], base_crop.shape[1])
                    if win_size % 2 == 0:
                        win_size -= 1
                    
                    if win_size >= 3:
                        score, ssim_map = structural_similarity(base_crop, current_crop, win_size=win_size, full=True)
                    else:
                        diff_map = cv2.absdiff(base_crop, current_crop)
                        score = 1.0 - (np.mean(diff_map) / 255.0)
                        ssim_map = 1.0 - (diff_map.astype(float) / 255.0)
                    
                    crop_area = float(bw * bh)
                    weighted_sum += float(score) * crop_area
                    total_weight += crop_area
                    
                    # Update binary mask using Otsu threshold on the local SSIM map
                    ssim_delta_crop = (1.0 - ssim_map) * 255.0
                    ssim_delta_crop = np.clip(ssim_delta_crop, 0, 255).astype(np.uint8)
                    ssim_delta_crop[ssim_delta_crop < 10] = 0
                    
                    # Compute Otsu threshold on local crop
                    if np.max(ssim_delta_crop) > 0:
                        _, ssim_binary_crop = cv2.threshold(ssim_delta_crop, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
                        
                        # Extract the original bounding box region from padded ssim_binary_crop
                        offset_x = bx - x1
                        offset_y = by - y1
                        orig_ssim_binary = ssim_binary_crop[offset_y : offset_y + bh, offset_x : offset_x + bw]
                        binary[by : by + bh, bx : bx + bw] = cv2.bitwise_or(binary[by : by + bh, bx : bx + bw], orig_ssim_binary)
            
            total_pixels = float(base_gray.size)
            unchanged_area = float(total_pixels - total_weight)
            ssim_score = float((weighted_sum + unchanged_area) / total_pixels)

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
    regions = _merge_nearby_regions(regions, merge_gap=20)
    regions.sort(key=lambda item: item.area, reverse=True)

    diff_pixels = int(np.count_nonzero(binary))
    total_pixels = int(binary.size)
    mismatch_pct = round((diff_pixels / total_pixels) * 100.0, 4)

    # Percy-style: tint changed pixels magenta/pink or yellow on current screenshot (no bounding boxes).
    overlay = current_canvas.copy().astype(np.float32)
    mask = binary > 0
    if highlight_style == "heatmap":
        # Heatmap based on diff delta intensity
        normalized = cv2.normalize(delta, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        heatmap = cv2.applyColorMap(normalized, cv2.COLORMAP_JET)
        alpha = (normalized / 255.0)[:, :, np.newaxis]
        overlay = overlay * (1.0 - alpha * 0.7) + heatmap.astype(np.float32) * (alpha * 0.7)
    elif highlight_style == "yellow":
        highlight_bgr = np.array([0, 255, 255], dtype=np.float32)
        overlay[mask] = overlay[mask] * 0.35 + highlight_bgr * 0.65
    else:
        highlight_bgr = np.array([180, 0, 255], dtype=np.float32)
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
    skip_ssim: bool = False,
    blur_radius: int = 3,
    highlight_style: str = "magenta",
) -> tuple[CompareResult, np.ndarray, np.ndarray]:
    baseline = _load_image(baseline_path)
    current = _load_image(current_path)
    if baseline.shape != current.shape:
        print(
            f"[Warning] Image dimension mismatch: baseline is {baseline.shape[1]}x{baseline.shape[0]}, "
            f"current is {current.shape[1]}x{current.shape[0]}. Automatically padding to match shapes.",
            flush=True
        )
    return compare_arrays(
        baseline=baseline,
        current=current,
        pixel_threshold=pixel_threshold,
        min_region_area=min_region_area,
        ignore_regions=ignore_regions,
        skip_ssim=skip_ssim,
        blur_radius=blur_radius,
        highlight_style=highlight_style,
    )



def _compare_images_worker(args):
    index, baseline_path, current_path, pixel_threshold, min_region_area, ignore_regions, skip_ssim, blur_radius, highlight_style = args
    try:
        res = compare_images(
            baseline_path=baseline_path,
            current_path=current_path,
            pixel_threshold=pixel_threshold,
            min_region_area=min_region_area,
            ignore_regions=ignore_regions,
            skip_ssim=skip_ssim,
            blur_radius=blur_radius,
            highlight_style=highlight_style,
        )
        return index, res
    except Exception as e:
        return index, e


def _compare_arrays_worker(args):
    index, baseline, current, pixel_threshold, min_region_area, ignore_regions, skip_ssim, blur_radius, highlight_style = args
    try:
        res = compare_arrays(
            baseline=baseline,
            current=current,
            pixel_threshold=pixel_threshold,
            min_region_area=min_region_area,
            ignore_regions=ignore_regions,
            skip_ssim=skip_ssim,
            blur_radius=blur_radius,
            highlight_style=highlight_style,
        )
        return index, res
    except Exception as e:
        return index, e


def compare_images_batch(
    pairs: Sequence[Tuple[Path, Path]],
    pixel_threshold: int = 20,
    min_region_area: int = 120,
    ignore_regions: Sequence[IgnoreRegion] = (),
    skip_ssim: bool = False,
    blur_radius: int = 3,
    highlight_style: str = "magenta",
    max_workers: int | None = None,
) -> list[Union[tuple[CompareResult, np.ndarray, np.ndarray], Exception]]:
    """Compare multiple image pairs concurrently using a persistent ProcessPoolExecutor."""
    total = len(pairs)
    if total == 0:
        return []

    effective_workers = max_workers or min(os.cpu_count() or 1, total, 8)
    logger.info("Batch compare start: %d pairs, %d workers", total, effective_workers)

    results: list[Union[tuple[CompareResult, np.ndarray, np.ndarray], Exception]] = [None] * total  # type: ignore[list-item]
    done_count = 0

    args_list = [
        (i, bp, cp, pixel_threshold, min_region_area, ignore_regions, skip_ssim, blur_radius, highlight_style)
        for i, (bp, cp) in enumerate(pairs)
    ]

    executor = None
    try:
        executor = get_persistent_process_pool(max_workers=effective_workers)
    except Exception as e:
        logger.warning("ProcessPoolExecutor unavailable, using ThreadPoolExecutor: %s", e)

    if executor is not None:
        try:
            futures = {
                executor.submit(_compare_images_worker, args): args[0]
                for args in args_list
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    _, res = future.result()
                    results[idx] = res
                except Exception as exc:
                    results[idx] = exc
                finally:
                    done_count += 1
                    logger.info("Batch compare: %d/%d", done_count, total)
        except Exception as e:
            logger.warning("ProcessPoolExecutor execution failed, falling back to ThreadPoolExecutor: %s", e)
            executor = None

    if executor is None:
        done_count = 0
        with ThreadPoolExecutor(max_workers=effective_workers) as tp_executor:
            def _run_one(index: int, baseline_path: Path, current_path: Path):
                return index, compare_images(
                    baseline_path=baseline_path,
                    current_path=current_path,
                    pixel_threshold=pixel_threshold,
                    min_region_area=min_region_area,
                    ignore_regions=ignore_regions,
                    skip_ssim=skip_ssim,
                    blur_radius=blur_radius,
                    highlight_style=highlight_style,
                )
            futures = {
                tp_executor.submit(_run_one, i, bp, cp): i
                for i, (bp, cp) in enumerate(pairs)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    _, res = future.result()
                    results[idx] = res
                except Exception as exc:
                    results[idx] = exc
                finally:
                    done_count += 1
                    logger.info("Batch compare fallback: %d/%d", done_count, total)

    return results


def compare_arrays_batch(
    baselines: list[np.ndarray],
    currents: list[np.ndarray],
    pixel_threshold: int = 20,
    min_region_area: int = 120,
    ignore_regions: Sequence[IgnoreRegion] = (),
    skip_ssim: bool = False,
    blur_radius: int = 3,
    highlight_style: str = "magenta",
    max_workers: int | None = None,
) -> list[Union[tuple[CompareResult, np.ndarray, np.ndarray], Exception]]:
    """Compare multiple pre-loaded numpy array pairs concurrently using a persistent ProcessPoolExecutor."""
    if len(baselines) != len(currents):
        raise ValueError(
            f"baselines and currents must have the same length "
            f"({len(baselines)} vs {len(currents)})"
        )

    total = len(baselines)
    if total == 0:
        return []

    effective_workers = max_workers or min(os.cpu_count() or 1, total, 8)
    logger.info("Array batch compare start: %d pairs, %d workers", total, effective_workers)

    results: list[Union[tuple[CompareResult, np.ndarray, np.ndarray], Exception]] = [None] * total  # type: ignore[list-item]
    done_count = 0

    args_list = [
        (i, b, c, pixel_threshold, min_region_area, ignore_regions, skip_ssim, blur_radius, highlight_style)
        for i, (b, c) in enumerate(zip(baselines, currents))
    ]

    executor = None
    try:
        executor = get_persistent_process_pool(max_workers=effective_workers)
    except Exception as e:
        logger.warning("ProcessPoolExecutor unavailable, using ThreadPoolExecutor: %s", e)

    if executor is not None:
        try:
            futures = {
                executor.submit(_compare_arrays_worker, args): args[0]
                for args in args_list
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    _, res = future.result()
                    results[idx] = res
                except Exception as exc:
                    results[idx] = exc
                finally:
                    done_count += 1
                    logger.info("Array batch compare: %d/%d", done_count, total)
        except Exception as e:
            logger.warning("ProcessPoolExecutor execution failed, falling back to ThreadPoolExecutor: %s", e)
            executor = None

    if executor is None:
        done_count = 0
        with ThreadPoolExecutor(max_workers=effective_workers) as tp_executor:
            def _run_one(index: int, baseline: np.ndarray, current: np.ndarray):
                return index, compare_arrays(
                    baseline=baseline,
                    current=current,
                    pixel_threshold=pixel_threshold,
                    min_region_area=min_region_area,
                    ignore_regions=ignore_regions,
                    skip_ssim=skip_ssim,
                    blur_radius=blur_radius,
                    highlight_style=highlight_style,
                )
            futures = {
                tp_executor.submit(_run_one, i, b, c): i
                for i, (b, c) in enumerate(zip(baselines, currents))
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    _, res = future.result()
                    results[idx] = res
                except Exception as exc:
                    results[idx] = exc
                finally:
                    done_count += 1
                    logger.info("Array batch compare fallback: %d/%d", done_count, total)

    return results
