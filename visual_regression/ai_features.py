from __future__ import annotations

from typing import Dict, Iterable, List, Sequence

import cv2
import numpy as np

from .models import CompareResult


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
