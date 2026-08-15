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
class MultiScaleResNet50Backbone(_ModuleBase):
    """ResNet50 feature extractor that pools and concatenates all four
    residual stages, instead of only the last.

    The single-scale backbone (`_build_resnet50_backbone`) already runs every
    stage — layer1 through layer4 are computed sequentially regardless, each
    one depends on the last — but only layer4's output, globally pooled down
    to a 7x7 map and averaged into one 2048-dim vector, ever reaches the
    classifier. Every stride-2 downsample along the way (224 -> 112 -> 56 ->
    28 -> 7) throws away spatial precision, and by layer4 a small localized
    change — a paragraph's text recoloured, one word's font swapped — has
    been averaged into a handful of pixels' worth of signal. That tracks: a
    single scalar (raw pixel mismatch magnitude) reproduces 83% of this
    project's deployed CNN's predictions, and its two weakest classes by a
    wide margin are exactly color-regression and font-change — the two
    defect types that are inherently small, localized, low-level, and have
    the least in common with the high-level, whole-image "what object is
    this" abstraction layer4 is built for.

    Pooling layer1 (256ch, 56x56), layer2 (512ch, 28x28) and layer3 (1024ch,
    14x14) too, and concatenating all four (256+512+1024+2048 = 3840-dim)
    gives the classifier the coarser, higher-resolution signal those earlier
    stages still carry, alongside the same layer4 semantics as before. This
    is the standard fix for perceptual-similarity tasks that need to notice
    small localized differences (LPIPS and similar work the same way, for
    the same reason) — the failure mode isn't under-trained weights, it's
    that the information such a paragraph's original colour was never
    forwarded to a place the classifier could use.

    Keeps the same freeze policy as the single-scale backbone (only layer4
    trainable) so a comparison against it isolates one variable — whether
    exposing the earlier stages helps at all — rather than also changing how
    much of the network is being fine-tuned.
    """

    def __init__(self, resnet_model):
        super().__init__()
        self.stem = nn.Sequential(
            resnet_model.conv1, resnet_model.bn1, resnet_model.relu, resnet_model.maxpool
        )
        self.layer1 = resnet_model.layer1
        self.layer2 = resnet_model.layer2
        self.layer3 = resnet_model.layer3
        self.layer4 = resnet_model.layer4
        self.pool = nn.AdaptiveAvgPool2d(1)

    def forward(self, x):
        x = self.stem(x)
        f1 = self.layer1(x)
        f2 = self.layer2(f1)
        f3 = self.layer3(f2)
        f4 = self.layer4(f3)
        pooled = [self.pool(f).flatten(1) for f in (f1, f2, f3, f4)]
        return torch.cat(pooled, dim=1)


def _build_resnet50_backbone_multiscale(pretrained: bool):
    """Same weights and freeze policy as `_build_resnet50_backbone`, wrapped
    so all four stages reach the classifier instead of only layer4. See
    `MultiScaleResNet50Backbone` for why."""
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

    feature_dim = 256 + 512 + 1024 + 2048  # layer1 + layer2 + layer3 + layer4
    backbone = MultiScaleResNet50Backbone(model)
    freeze_backbone = weights_source == "imagenet-default"
    for name, parameter in backbone.named_parameters():
        if "layer4" in name:
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

    if backbone_name == "resnet50_multiscale":
        return _build_resnet50_backbone_multiscale(pretrained=pretrained)

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
# How wide the rule features are made before they meet the image embedding.
# Concatenated raw, 74 columns sit beside 8192 image columns — 0.9% of the input
# — and a single Linear has little reason to weight them. Projecting them first
# gives them a comparable share and their own non-linearity, so "the strokes
# changed but the hue did not" can be composed before the image drowns it out.
RULE_PROJECTION_DIM = 256

# Projecting the image side to the rule side's width, so neither pathway is 32x
# the other. Off by default: it did what it was built to do and that turned out
# not to be the constraint.
#
# Measured (v6, 3605 pairs): the head went from 8.96M parameters to 2.93M and the
# train/val ratio from 3.6x to 1.1x — the overfitting was gone. Accuracy did not
# follow. Validation stayed at 35.1% against v5's 37.1%, and no-DOM evaluation
# fell from 37.0% to 28.2%. What limits the pixel-only case is that the model is
# trained with DOM features always present and then asked to work with 53 of its
# 77 columns zeroed: a controlled test put that shift at 91.2% -> 60.0%, and
# training with dom_dropout recovers it to 79.5%.
#
# Kept, with its tests, because it is correct and cheap to switch on; a run that
# is genuinely overfitting can set it.
IMAGE_PROJECTION_DIM = None


class _RuleProjectingHead:
    """Fusion head that widens the rule vector before concatenating it.

    Deliberately consumes the same single concatenated tensor the old head did
    — image streams first, rule features last — so every call site
    (`head(torch.cat([...]))`), the training loop, all three inference paths and
    the ONNX/TorchScript exporters keep working untouched. It splits the tensor
    itself using the rule width it was built with.
    """

    def __init__(self, nn_module, torch_module, image_dim: int, rule_dim: int,
                 output_dim: int, projection_dim: int = RULE_PROJECTION_DIM,
                 image_projection_dim: "int | None" = IMAGE_PROJECTION_DIM):
        self._torch = torch_module
        self.rule_dim = rule_dim
        self.rule_proj = nn_module.Sequential(
            nn_module.Linear(rule_dim, 128),
            nn_module.BatchNorm1d(128),
            nn_module.ReLU(),
            nn_module.Linear(128, projection_dim),
            nn_module.ReLU(),
        )
        # The image streams arrive as 8192 dimensions against the rule vector's
        # 77, and the trunk's first layer was Linear(8448, 1024) — 8.65M weights,
        # nearly all of them fed by pixels. That is capacity to memorise with,
        # and measurement says it is being used that way: train loss 0.499
        # against val loss 1.788, while a small model over the same 24 pixel
        # statistics reaches 82.0% without DOM where this head reaches 37.0%.
        # The evidence is not that the images are useless — it is that 8192
        # dimensions of them drown 77 dimensions of explicit evidence.
        #
        # Projecting the image side down to match puts the two pathways on
        # comparable footing and removes most of what was available for
        # memorisation. None restores the previous architecture exactly, which
        # is what every checkpoint trained before this needs.
        self.image_proj = None
        trunk_in = image_dim + projection_dim
        if image_projection_dim:
            self.image_proj = nn_module.Sequential(
                nn_module.Linear(image_dim, image_projection_dim),
                nn_module.BatchNorm1d(image_projection_dim),
                nn_module.ReLU(),
                nn_module.Dropout(0.30),
            )
            trunk_in = image_projection_dim + projection_dim
        self.trunk = nn_module.Sequential(
            nn_module.Linear(trunk_in, 1024),
            nn_module.BatchNorm1d(1024),
            nn_module.ReLU(),
            nn_module.Dropout(0.15),
            nn_module.Linear(1024, 256),
            nn_module.BatchNorm1d(256),
            nn_module.ReLU(),
            nn_module.Dropout(0.08),
            nn_module.Linear(256, output_dim),
        )
        modules = {"rule_proj": self.rule_proj, "trunk": self.trunk}
        if self.image_proj is not None:
            modules["image_proj"] = self.image_proj
        self.model = nn_module.ModuleDict(modules)

        def _forward(combined):
            image = combined[:, : -self.rule_dim]
            rule = combined[:, -self.rule_dim:]
            if self.image_proj is not None:
                image = self.image_proj(image)
            return self.trunk(torch_module.cat([image, self.rule_proj(rule)], dim=1))

        self.model.forward = _forward


class SiameseFusionHead:  
    def __init__(self, nn_module, embedding_dim: int, rule_dim: int, output_dim: int,
                 num_streams: int = 4, widen_rule_features: bool = True,
                 image_projection_dim: "int | None" = IMAGE_PROJECTION_DIM):
        image_dim = embedding_dim * num_streams
        if widen_rule_features:
            from .ai_models import _RuleProjectingHead as _RPH  # self-reference, kept explicit
            import torch as _torch
            # image_projection_dim=None reproduces the head as it was before the
            # image side was projected. Checkpoints trained then carry no
            # image_proj weights, and building one for them fails the load.
            self.model = _RPH(nn_module, _torch, image_dim, rule_dim, output_dim,
                              image_projection_dim=image_projection_dim).model
            return
        self.model = nn_module.Sequential(
            nn_module.Linear(image_dim + rule_dim, 1024),
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
        product = left_embedding * right_embedding
        combined = self._concat(left_embedding, right_embedding, distance, product, rule_features)
        return self.model(combined)

    @staticmethod
    def _concat(left_embedding, right_embedding, distance, product, rule_features):
        import torch

        return torch.cat([left_embedding, right_embedding, distance, product, rule_features], dim=1)
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
            # A widened head (SiameseFusionHead(widen_rule_features=True)) is a
            # ModuleDict registering rule_proj before trunk, so
            # next(self.head.parameters()) picks up rule_proj.0.weight —
            # shape[1] == rule_dim (a few dozen), not the image width the trunk
            # actually expects. That read as "small head" and fell through to
            # the 3-stream branch, so torch.onnx.export ran the model with the
            # diff-image stream missing and the head's first matmul saw 6400
            # columns where the trunk was built for 8448 (4 streams x 2048 +
            # the 256-wide rule projection). Preferring a state-dict entry
            # under "trunk." — the layer that actually receives this
            # concatenation — is what the correct-but-slower fallback branch
            # below already computes; try it first when it is available.
            head_state = self.head.state_dict()
            trunk_key = next((k for k in head_state if k.startswith("trunk.")
                              and head_state[k].dim() == 2), None)
            if trunk_key is not None:
                expected_dim = head_state[trunk_key].shape[1]
            else:
                expected_dim = next(self.head.parameters()).shape[1]
        except Exception:
            expected_dim = (emb_dim * 3) + rule_features.shape[1]

        if expected_dim >= (emb_dim * 4):
            diff_img = torch.abs(left_image - right_image)
            diff_emb = self.backbone(diff_img).flatten(1)
            combined = torch.cat([left_emb, right_emb, distance, diff_emb, rule_features], dim=1)
        else:
            combined = torch.cat([left_emb, right_emb, distance, rule_features], dim=1)
        return self.head(combined)
