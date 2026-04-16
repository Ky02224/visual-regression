from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

import cv2
import numpy as np

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

DEFECT_LABELS = [
    "insignificant-change",
    "missing-element",
    "layout-shift",
    "color-regression",
    "text-truncation",
    "overlay-obstruction",
]
DEFECT_LABEL_TO_INDEX = {label: idx for idx, label in enumerate(DEFECT_LABELS)}
DEFECT_MODES = [
    "missing_element",
    "layout_shift",
    "color_regression",
    "text_truncation",
    "overlay_obstruction",
]
DEFECT_MODE_WEIGHTS = {
    "missing_element": 2,
    "layout_shift": 2,
    "color_regression": 3,
    "text_truncation": 3,
    "overlay_obstruction": 2,
}
DEFECT_MODE_TO_LABEL = {
    "missing_element": "missing-element",
    "layout_shift": "layout-shift",
    "color_regression": "color-regression",
    "text_truncation": "text-truncation",
    "overlay_obstruction": "overlay-obstruction",
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


def _load_base_images(paths: WorkspacePaths) -> List[np.ndarray]:
    bases: List[np.ndarray] = []
    for baseline_dir in paths.baselines_dir.iterdir():
        image_path = baseline_dir / "baseline.png"
        if not image_path.exists():
            continue
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is not None:
            bases.append(image)
    if bases:
        return bases
    return [_draw_base_ui(seed) for seed in range(6)]


def _load_public_dataset_images(manifest_path: Path | None, max_images: int | None = None) -> List[np.ndarray]:
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
        images.append(image)
    return images


def _apply_benign_variant(image: np.ndarray, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    variant = image.copy().astype(np.float32)
    brightness = rng.uniform(-4.0, 4.0)
    variant += brightness
    noise = rng.normal(0.0, 1.2, size=variant.shape)
    variant += noise
    variant = np.clip(variant, 0, 255).astype(np.uint8)
    if seed % 3 == 0:
        variant = cv2.GaussianBlur(variant, (3, 3), 0)
    return variant


def _apply_defect_variant(image: np.ndarray, seed: int, mode: str | None = None) -> tuple[np.ndarray, str]:
    rng = random.Random(seed)
    variant = image.copy()
    mode = mode or rng.choice(DEFECT_MODES)

    if mode == "missing_element":
        cv2.rectangle(variant, (520, 160), (690, 270), (248, 248, 248), thickness=-1)
        label = "missing-element"
    elif mode == "color_regression":
        cv2.rectangle(variant, (0, 0), (variant.shape[1], 88), (22, 50, 148), thickness=-1)
        cv2.rectangle(variant, (520, 160), (690, 270), (36, 146, 210), thickness=-1)
        cv2.rectangle(variant, (720, 160), (890, 270), (210, 234, 255), thickness=-1)
        label = "color-regression"
    elif mode == "layout_shift":
        panel = variant[116:820, 396:variant.shape[1] - 40].copy()
        shift = min(30, panel.shape[1] // 8)
        shifted = np.full_like(panel, 255)
        shifted[:, shift:] = panel[:, : panel.shape[1] - shift]
        variant[116:820, 396:variant.shape[1] - 40] = shifted
        label = "layout-shift"
    elif mode == "overlay_obstruction":
        x = rng.randint(470, 980)
        y = rng.randint(260, 620)
        cv2.rectangle(variant, (x, y), (x + 220, y + 120), (24, 24, 24), thickness=-1)
        label = "overlay-obstruction"
    elif mode == "text_truncation":
        for idx in range(5):
            top = 336 + idx * 72
            line_width = 300 + ((idx % 2) * 70)
            cv2.rectangle(variant, (780, top), (780 + line_width, top + 18), (223, 228, 235), thickness=-1)
            cv2.rectangle(variant, (1040, top - 2), (1240, top + 22), (255, 255, 255), thickness=-1)
        cv2.rectangle(variant, (760, 332), (780, 332 + (5 * 72)), (255, 255, 255), thickness=-1)
        label = "text-truncation"
    return variant, label


@dataclass
class PairSample:
    baseline_rgb: np.ndarray
    current_rgb: np.ndarray
    rule_features: np.ndarray
    label_index: int
    label_name: str


def _build_pair_sample(
    baseline: np.ndarray,
    current: np.ndarray,
    pixel_threshold: int,
    min_region_area: int,
    label_name: str,
) -> PairSample:
    result, _, _ = compare_arrays(
        baseline=baseline,
        current=current,
        pixel_threshold=pixel_threshold,
        min_region_area=min_region_area,
        ignore_regions=[],
    )
    return PairSample(
        baseline_rgb=ensure_rgb_batch([baseline])[0],
        current_rgb=ensure_rgb_batch([current])[0],
        rule_features=feature_vector_from_result(result),
        label_index=DEFECT_LABEL_TO_INDEX[label_name],
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
            payload = json.loads(result_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        status = str(payload.get("status") or "").upper()
        if status not in {"PASS", "FAIL"}:
            continue

        baseline_image = cv2.imread(str(baseline_path), cv2.IMREAD_COLOR)
        current_image = cv2.imread(str(current_path), cv2.IMREAD_COLOR)
        if baseline_image is None or current_image is None:
            continue

        if status == "PASS":
            label_name = "insignificant-change"
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


def build_synthetic_dataset(
    paths: WorkspacePaths,
    samples_per_image: int,
    pixel_threshold: int,
    min_region_area: int,
    dataset_manifest_path: Path | None = None,
    max_public_images: int | None = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    samples: List[PairSample] = []
    base_images = _load_base_images(paths)
    public_images = _load_public_dataset_images(dataset_manifest_path, max_images=max_public_images)
    if public_images:
        base_images.extend(public_images)

    sample_seed = 0
    for base in base_images:
        for _ in range(samples_per_image):
            good_variant = _apply_benign_variant(base, sample_seed)
            samples.append(
                _build_pair_sample(
                    baseline=base,
                    current=good_variant,
                    pixel_threshold=pixel_threshold,
                    min_region_area=min_region_area,
                    label_name="insignificant-change",
                )
            )
            for defect_mode in DEFECT_MODES:
                repeat = DEFECT_MODE_WEIGHTS.get(defect_mode, 1)
                for repeat_index in range(repeat):
                    bad_variant, defect_label = _apply_defect_variant(
                        base,
                        sample_seed + 10_000 + repeat_index,
                        mode=defect_mode,
                    )
                    sample_seed += 1
                    samples.append(
                        _build_pair_sample(
                            baseline=base,
                            current=bad_variant,
                            pixel_threshold=pixel_threshold,
                            min_region_area=min_region_area,
                            label_name=defect_label,
                        )
                    )

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
    for parameter in backbone.parameters():
        parameter.requires_grad = not freeze_backbone
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


class SiameseFusionHead:  # pragma: no cover - exercised through train/infer flow
    def __init__(self, nn_module, embedding_dim: int, rule_dim: int, output_dim: int):
        self.model = nn_module.Sequential(
            nn_module.Linear((embedding_dim * 3) + rule_dim, 1024),
            nn_module.ReLU(),
            nn_module.Dropout(0.2),
            nn_module.Linear(1024, 256),
            nn_module.ReLU(),
            nn_module.Dropout(0.1),
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


def _heuristic_defect_label(result: CompareResult, baseline_image: np.ndarray, current_image: np.ndarray) -> str:
    region_count = len(result.regions)
    if result.mismatch_pct < 0.2 and region_count <= 1:
        return "insignificant-change"
    if not result.regions:
        return "insignificant-change"

    total_pixels = float(max(result.total_pixels, 1))
    largest = max(result.regions, key=lambda region: region.area)
    largest_ratio = float(largest.area) / total_pixels
    thin_bands = [region for region in result.regions if region.height <= 36 and region.width >= 140]
    aligned_bands = [region for region in thin_bands if region.x >= int(baseline_image.shape[1] * 0.45)]
    if len(aligned_bands) >= 3:
        return "text-truncation"

    y_end = min(largest.y + largest.height, baseline_image.shape[0])
    x_end = min(largest.x + largest.width, baseline_image.shape[1])
    baseline_crop = baseline_image[largest.y:y_end, largest.x:x_end]
    current_crop = current_image[largest.y:y_end, largest.x:x_end]
    if baseline_crop.size and current_crop.size:
        color_delta = float(np.mean(np.abs(baseline_crop.astype(np.float32) - current_crop.astype(np.float32))))
        current_brightness = float(np.mean(current_crop))
        if largest.y < 140 and largest.width >= int(baseline_image.shape[1] * 0.55) and color_delta >= 18.0:
            return "color-regression"
        if color_delta >= 22.0 and largest_ratio <= 0.04 and region_count <= 4:
            return "color-regression"
        if current_brightness <= 60.0 and largest_ratio >= 0.02:
            return "overlay-obstruction"

    if region_count >= 6 or largest_ratio >= 0.05:
        return "layout-shift"
    return "missing-element"


def _encode_batch(torch_module, backbone, batch_rgb: np.ndarray, device: str, track_grad: bool = False):
    tensor = torch_module.tensor(normalize_batch_uint8(batch_rgb), dtype=torch_module.float32, device=device)
    if not track_grad:
        with torch_module.no_grad():
            embedding = backbone(tensor).flatten(1)
        return embedding
    else:
        embedding = backbone(tensor).flatten(1)
    return embedding


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

    baseline_images, current_images, rule_features, labels = build_synthetic_dataset(
        paths=paths,
        samples_per_image=samples_per_image,
        pixel_threshold=pixel_threshold,
        min_region_area=min_region_area,
        dataset_manifest_path=dataset_manifest_path,
        max_public_images=max_public_images,
    )

    permutation = np.random.permutation(len(labels))
    baseline_images = baseline_images[permutation]
    current_images = current_images[permutation]
    rule_features = rule_features[permutation]
    labels = labels[permutation]

    split_idx = max(1, int(len(labels) * 0.8))
    if split_idx >= len(labels):
        split_idx = max(1, len(labels) - 1)

    x_left_train = baseline_images[:split_idx]
    x_right_train = current_images[:split_idx]
    x_rule_train = rule_features[:split_idx]
    y_train = labels[:split_idx]

    x_left_val = baseline_images[split_idx:]
    x_right_val = current_images[split_idx:]
    x_rule_val = rule_features[split_idx:]
    y_val = labels[split_idx:]

    device = "cpu"
    backbone, embedding_dim, weights_source, freeze_backbone = _build_resnet50_backbone(pretrained=pretrained_backbone)
    backbone = backbone.to(device)

    head = SiameseFusionHead(
        nn,
        embedding_dim=embedding_dim,
        rule_dim=rule_features.shape[1],
        output_dim=len(DEFECT_LABELS),
    ).model.to(device)
    parameters = list(head.parameters())
    if not freeze_backbone:
        backbone.train()
        parameters.extend(backbone.parameters())
    optimizer = torch.optim.Adam(parameters, lr=learning_rate)
    class_counts = np.bincount(y_train, minlength=len(DEFECT_LABELS)).astype(np.float32)
    class_counts[class_counts == 0.0] = 1.0
    class_weights = class_counts.sum() / class_counts
    class_weights = class_weights / class_weights.mean()
    criterion = nn.CrossEntropyLoss(weight=torch.tensor(class_weights, dtype=torch.float32, device=device))

    for _ in range(epochs):
        order = np.random.permutation(len(x_left_train))
        head.train()
        if freeze_backbone:
            backbone.eval()
        else:
            backbone.train()
        for start in range(0, len(order), batch_size):
            idx = order[start : start + batch_size]
            left_embedding = _encode_batch(torch, backbone, x_left_train[idx], device, track_grad=not freeze_backbone)
            right_embedding = _encode_batch(torch, backbone, x_right_train[idx], device, track_grad=not freeze_backbone)
            rule_batch = torch.tensor(x_rule_train[idx], dtype=torch.float32, device=device)
            distance = (left_embedding - right_embedding).abs()
            combined = torch.cat([left_embedding, right_embedding, distance, rule_batch], dim=1)

            logits = head(combined)
            target = torch.tensor(y_train[idx], dtype=torch.long, device=device)
            optimizer.zero_grad()
            loss = criterion(logits, target)
            loss.backward()
            optimizer.step()

    head.eval()
    if len(x_left_val):
        with torch.no_grad():
            left_embedding = _encode_batch(torch, backbone, x_left_val, device)
            right_embedding = _encode_batch(torch, backbone, x_right_val, device)
            rule_batch = torch.tensor(x_rule_val, dtype=torch.float32, device=device)
            combined = torch.cat([left_embedding, right_embedding, (left_embedding - right_embedding).abs(), rule_batch], dim=1)
            val_logits = head(combined)
            val_preds = torch.argmax(val_logits, dim=1)
            val_targets = torch.tensor(y_val, dtype=torch.long, device=device)
            accuracy = float((val_preds.eq(val_targets)).float().mean().item())
            metrics = _compute_multiclass_metrics(
                y_true=y_val,
                y_pred=val_preds.cpu().numpy(),
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
        "backbone_state_dict": backbone.state_dict(),
        "classifier_state_dict": head.state_dict(),
        "accuracy": accuracy,
        "samples": int(len(labels)),
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
        "samples": int(len(labels)),
        "epochs": epochs,
        "image_size": DEFAULT_IMAGE_SIZE,
        "backbone": "resnet50",
        "dataset_manifest": str(dataset_manifest_path) if dataset_manifest_path else None,
        "public_images_used": int(len(public_images := _load_public_dataset_images(dataset_manifest_path, max_images=max_public_images))) if dataset_manifest_path else 0,
        "evaluation": metrics,
    }
    metadata_path = model_path.with_suffix(".json")
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    eval_path = paths.reports_dir / f"ai-eval-{model_path.stem}.json"
    eval_payload = {
        "model_path": str(model_path),
        "class_names": DEFECT_LABELS,
        "evaluation": metrics,
        "samples": int(len(labels)),
        "dataset_manifest": str(dataset_manifest_path) if dataset_manifest_path else None,
    }
    eval_path.write_text(json.dumps(eval_payload, indent=2), encoding="utf-8")
    return metadata


def _load_legacy_or_hybrid_model(model_path: Path):
    torch, nn = _require_torch()
    checkpoint = torch.load(model_path, map_location="cpu")
    model_type = str(checkpoint.get("model_type") or "legacy-rule-mlp")

    if model_type == "legacy-rule-mlp" or "classifier_state_dict" not in checkpoint:
        return {
            "type": "legacy",
            "runner": LegacyRuleMLP(torch, nn, checkpoint),
            "threshold": float(checkpoint.get("threshold", 0.5)),
        }

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
    return {
        "type": "hybrid-multiclass" if class_names else "hybrid-binary",
        "torch": torch,
        "backbone": backbone,
        "head": head,
        "threshold": float(checkpoint.get("threshold", 0.5)),
        "image_size": int(checkpoint.get("image_size", DEFAULT_IMAGE_SIZE)),
        "model_type": model_type,
        "class_names": class_names,
    }


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
        label = "meaningful-change" if score >= threshold else "insignificant-change"
        return AIAssessment(
            score=round(score, 6),
            label=label,
            threshold=threshold,
            model_name=model_path.name,
        )

    if not baseline_image_path or not current_image_path:
        raise ValueError("Hybrid AI assessment requires baseline and current image paths.")

    baseline_image = cv2.imread(str(baseline_image_path), cv2.IMREAD_COLOR)
    current_image = cv2.imread(str(current_image_path), cv2.IMREAD_COLOR)
    if baseline_image is None or current_image is None:
        raise ValueError("Failed to read baseline/current images for hybrid AI assessment.")

    torch = loaded["torch"]
    baseline_batch = ensure_rgb_batch([baseline_image], image_size=int(loaded["image_size"]))
    current_batch = ensure_rgb_batch([current_image], image_size=int(loaded["image_size"]))
    left_embedding = _encode_batch(torch, loaded["backbone"], baseline_batch, "cpu")
    right_embedding = _encode_batch(torch, loaded["backbone"], current_batch, "cpu")
    rule_vector = torch.tensor(feature_vector_from_result(result), dtype=torch.float32).unsqueeze(0)

    with torch.no_grad():
        combined = torch.cat([left_embedding, right_embedding, (left_embedding - right_embedding).abs(), rule_vector], dim=1)
        logits = loaded["head"](combined)
        if loaded["type"] == "hybrid-binary":
            score = float(torch.sigmoid(logits).item())
            threshold = float(loaded["threshold"])
            label = "meaningful-change" if score >= threshold else "insignificant-change"
        else:
            probabilities = torch.softmax(logits, dim=1).squeeze(0)
            top_index = int(torch.argmax(probabilities).item())
            score = float(probabilities[top_index].item())
            threshold = float(loaded["threshold"])
            label = loaded["class_names"][top_index]
            if score < threshold:
                label = _heuristic_defect_label(result, baseline_image, current_image)
    return AIAssessment(
        score=round(score, 6),
        label=label,
        threshold=threshold,
        model_name=model_path.name,
    )


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
        label_name = assessment.label if assessment.label in DEFECT_LABEL_TO_INDEX else "insignificant-change"
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
