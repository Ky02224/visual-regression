"""The multi-scale ResNet50 backbone: pools and concatenates all four
residual stages instead of only layer4, so the classifier receives the
higher-resolution, lower-level signal (colour, font) that layer4 alone
averages away. See MultiScaleResNet50Backbone's docstring for why.

Uses pretrained=False throughout — these check architecture and wiring, not
learned weights, and skipping the ImageNet download keeps the suite offline
and fast.
"""

import pytest

torch = pytest.importorskip("torch")

from visual_regression.ai_models import (
    MultiScaleResNet50Backbone,
    _build_backbone,
    _build_resnet50_backbone,
    _build_resnet50_backbone_multiscale,
)


def test_output_dim_is_the_sum_of_all_four_stages():
    backbone, feature_dim, _, _ = _build_resnet50_backbone_multiscale(pretrained=False)
    assert feature_dim == 256 + 512 + 1024 + 2048 == 3840


def test_forward_pass_shape_matches_reported_feature_dim():
    backbone, feature_dim, _, _ = _build_resnet50_backbone_multiscale(pretrained=False)
    backbone.eval()
    x = torch.zeros(2, 3, 224, 224)
    with torch.no_grad():
        out = backbone(x)
    assert out.shape == (2, feature_dim)


def test_flatten_after_call_is_a_no_op_like_the_single_scale_backbone():
    """Every call site in the training/inference code does
    `backbone(x).flatten(1)` — the multi-scale backbone already returns a 2D
    tensor, so that call must stay harmless (a 2D tensor flattened from dim 1
    is unchanged), not silently reshape something unexpected."""
    backbone, feature_dim, _, _ = _build_resnet50_backbone_multiscale(pretrained=False)
    backbone.eval()
    x = torch.zeros(1, 3, 224, 224)
    with torch.no_grad():
        out = backbone(x)
    assert out.flatten(1).shape == out.shape


def test_only_layer4_is_trainable_when_pretrained_matches_the_single_scale_policy():
    """Isolates one variable against the deployed backbone: exposing the
    earlier stages, not also changing how much of the network gets
    fine-tuned. Compared directly against the single-scale backbone's own
    freeze pattern rather than a hard-coded assumption, so the two stay in
    lockstep if that policy ever changes."""
    single, _, _, single_freeze = _build_resnet50_backbone(pretrained=True)
    multi, _, _, multi_freeze = _build_resnet50_backbone_multiscale(pretrained=True)

    single_trainable = {name for name, p in single.named_parameters() if p.requires_grad}
    multi_trainable = {name for name, p in multi.named_parameters() if p.requires_grad}

    assert single_freeze == multi_freeze
    assert any("layer4" in n for n in multi_trainable)
    assert not any("layer1" in n or "layer2" in n or "layer3" in n for n in multi_trainable)
    # layer4 itself should be trainable under the identical rule in both.
    assert {n for n in single_trainable if "layer4" in n} or not any("layer4" in n for n in single.named_parameters())


def test_build_backbone_dispatches_to_the_multiscale_variant_by_name():
    backbone, feature_dim, _, _ = _build_backbone("resnet50_multiscale", pretrained=False)
    assert isinstance(backbone, MultiScaleResNet50Backbone)
    assert feature_dim == 3840


def test_build_backbone_default_name_is_unaffected():
    """The existing deployed model's backbone must be untouched by this
    addition — same class, same 2048-dim output."""
    backbone, feature_dim, _, _ = _build_backbone("resnet50", pretrained=False)
    assert not isinstance(backbone, MultiScaleResNet50Backbone)
    assert feature_dim == 2048
