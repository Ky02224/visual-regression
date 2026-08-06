"""Model architecture and the torch/torchvision import guards.

Split out of ai_training.py, which had grown to ~3200 lines mixing the network
definition, the training loop, inference, evaluation and ONNX export. These are
the pieces that describe *what the model is*, with no opinion about how it is
trained or used — which is what lets ai_export import them without dragging in
the training machinery.

torch is imported lazily throughout. It is a large optional dependency, and the
CLI's non-AI commands must work without it installed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict

import numpy as np

from .ai_features import feature_vector_from_result
from .models import CompareResult

logger = logging.getLogger(__name__)

# torch is an optional dependency: the CLI's non-AI commands must work without
# it. CompleteSiameseModel has to subclass nn.Module when it is available and
# something harmless when it is not, so the base is resolved at import time and
# the class definition below stays valid either way.
try:
    import torch
    import torch.nn as nn

    _ModuleBase = nn.Module
except ImportError:  # pragma: no cover - exercised only on installs without torch
    torch = None
    nn = None
    _ModuleBase = object


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
@dataclass
class PairSample:
    baseline_rgb: np.ndarray
    current_rgb: np.ndarray
    rule_features: np.ndarray
    label_index: int
    label_name: str
    dom_features: "np.ndarray | None" = None  # Optional DOM features for multimodal training
    # Pixel-derived structural signals. Unlike dom_features these survive a
    # screenshot-only comparison, which is the case they exist for.
    pixel_features: "np.ndarray | None" = None
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
def _build_backbone(backbone_name: str, pretrained: bool):
    _, nn = _require_torch()
    if backbone_name == "efficientnet_b3":
        try:
            from torchvision.models import efficientnet_b3, EfficientNet_B3_Weights
            weights = EfficientNet_B3_Weights.DEFAULT if pretrained else None
            model = efficientnet_b3(weights=weights)
            feature_dim = int(model.classifier[1].in_features) # 1536
            backbone = nn.Sequential(
                model.features,
                model.avgpool
            )
            freeze_backbone = pretrained
            if pretrained:
                for name, parameter in backbone.named_parameters():
                    if any(x in name for x in [".6.", ".7.", ".8."]):
                        parameter.requires_grad = True
                    else:
                        parameter.requires_grad = False
            else:
                for parameter in backbone.parameters():
                    parameter.requires_grad = True
            weights_source = "efficientnet-b3-imagenet" if pretrained else "random-init"
            return backbone, feature_dim, weights_source, freeze_backbone
        except Exception as exc:
            logger.warning("Failed to load EfficientNet-B3 backbone (%s). Falling back to ResNet50.", exc)
            
    return _build_resnet50_backbone(pretrained=pretrained)
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
    def __init__(self, nn_module, embedding_dim: int, rule_dim: int, output_dim: int, num_streams: int = 4):
        self.model = nn_module.Sequential(
            nn_module.Linear((embedding_dim * num_streams) + rule_dim, 1024),
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
class CompleteSiameseModel(_ModuleBase):
    def __init__(self, backbone, head):
        super().__init__()
        self.backbone = backbone
        self.head = head

    def forward(self, left_image, right_image, rule_features):
        left_emb = self.backbone(left_image).flatten(1)
        right_emb = self.backbone(right_image).flatten(1)
        distance = (left_emb - right_emb).abs()

        emb_dim = left_emb.shape[1]
        try:
            head_first = next(self.head.parameters())
            expected_dim = head_first.shape[1]
        except Exception:
            expected_dim = (emb_dim * 3) + rule_features.shape[1]

        if expected_dim >= (emb_dim * 4):
            diff_img = torch.abs(left_image - right_image)
            diff_emb = self.backbone(diff_img).flatten(1)
            combined = torch.cat([left_emb, right_emb, distance, diff_emb, rule_features], dim=1)
        else:
            combined = torch.cat([left_emb, right_emb, distance, rule_features], dim=1)
        return self.head(combined)
