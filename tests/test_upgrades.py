import numpy as np
from unittest.mock import MagicMock, patch

from visual_regression.ai_features import are_images_identical_hash
from visual_regression.ai_training import CompleteSiameseModel, SiameseFusionHead
from visual_regression.config import WorkspacePaths
from visual_regression.dashboard_server import queue_ai_training_sample


def test_ahash_and_perceptual_identical_check():
    # Construct two identical black images
    img1 = np.zeros((100, 100, 3), dtype=np.uint8)
    img2 = np.zeros((100, 100, 3), dtype=np.uint8)

    # They should be perceptually identical
    assert are_images_identical_hash(img1, img2, threshold=2) is True

    # Change a tiny region (1 pixel) - should still be below threshold
    img2[0, 0] = (255, 255, 255)
    assert are_images_identical_hash(img1, img2, threshold=2) is True

    # Fill a large part of the image (change significantly)
    img2[0:50, 0:50] = (255, 255, 255)
    assert are_images_identical_hash(img1, img2, threshold=2) is False


def test_siamese_fusion_head_num_streams():
    """The stream count must decide how much image data the head expects.

    Checked on the flat head, whose first Linear takes the concatenation
    directly. The widened head is covered by test_widened_fusion_head.py: it
    projects the rule columns first, so its trunk width is image + projection
    and the raw rule width no longer appears there.
    """
    import torch.nn as nn

    head_4 = SiameseFusionHead(nn, embedding_dim=10, rule_dim=5, output_dim=2,
                               num_streams=4, widen_rule_features=False)
    assert head_4.model[0].in_features == (10 * 4) + 5

    head_3 = SiameseFusionHead(nn, embedding_dim=10, rule_dim=5, output_dim=2,
                               num_streams=3, widen_rule_features=False)
    assert head_3.model[0].in_features == (10 * 3) + 5


def test_widened_head_still_scales_with_num_streams():
    """Same property, expressed where the widened head keeps it: the trunk sees
    every image stream plus the projected rule vector."""
    import torch.nn as nn

    from visual_regression.ai_models import RULE_PROJECTION_DIM

    for streams in (3, 4):
        head = SiameseFusionHead(nn, embedding_dim=10, rule_dim=5, output_dim=2,
                                 num_streams=streams)
        trunk_in = head.model.state_dict()["trunk.0.weight"].shape[1]
        assert trunk_in == (10 * streams) + RULE_PROJECTION_DIM


def test_complete_siamese_model_dynamic_forward():
    import torch
    import torch.nn as nn

    # Mock backbone
    backbone = MagicMock(return_value=torch.zeros(1, 10))

    # Mock head expecting 3 streams (emb_dim * 3 + rule_dim = 30 + 5 = 35)
    head_3 = nn.Sequential(nn.Linear(35, 2))
    model_3 = CompleteSiameseModel(backbone, head_3)

    left = torch.zeros(1, 3, 224, 224)
    right = torch.zeros(1, 3, 224, 224)
    rules = torch.zeros(1, 5)

    # 3-stream forward execution should not crash and call backbone exactly twice (left, right)
    out_3 = model_3(left, right, rules)
    assert out_3.shape == (1, 2)
    assert backbone.call_count == 2

    # Reset mock
    backbone.reset_mock()

    # Mock head expecting 4 streams (emb_dim * 4 + rule_dim = 40 + 5 = 45)
    head_4 = nn.Sequential(nn.Linear(45, 2))
    model_4 = CompleteSiameseModel(backbone, head_4)

    # 4-stream forward execution should call backbone three times (left, right, abs(left-right))
    out_4 = model_4(left, right, rules)
    assert out_4.shape == (1, 2)
    assert backbone.call_count == 3


@patch("visual_regression.dashboard_server._run_background_ai_training")
def test_active_learning_incremental_fine_tuning_trigger(mock_train_background, tmp_path):
    # Setup paths
    paths = WorkspacePaths(root=tmp_path)
    paths.ensure()

    # Empty active learning directory - should not trigger
    queue_ai_training_sample(paths)
    mock_train_background.assert_not_called()

    # Create active learning directory
    al_dir = paths.root / "active_learning"
    al_dir.mkdir(parents=True, exist_ok=True)

    # Populate 10 fake reviewed JSON files
    for i in range(10):
        (al_dir / f"run_{i}.json").write_text("{}", encoding="utf-8")

    # First call only seeds .last_trained_count. Without that step a workspace
    # whose counter file is missing reads its whole existing backlog as new and
    # fires a full retrain on the next single review — observed on a real
    # workspace holding 9 historical reviews and no counter.
    queue_ai_training_sample(paths)
    mock_train_background.assert_not_called()
    assert (al_dir / ".last_trained_count").read_text(encoding="utf-8").strip() == "10"

    # Ten *new* reviews after that do trigger it.
    for i in range(10, 20):
        (al_dir / f"run_{i}.json").write_text("{}", encoding="utf-8")
    queue_ai_training_sample(paths)

    mock_train_background.assert_called_once()
