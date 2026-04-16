import numpy as np

from visual_regression.ai_features import (
    DEFAULT_IMAGE_SIZE,
    ensure_rgb_batch,
    normalize_batch_uint8,
)


def test_prepare_and_normalize_backbone_batch():
    image = np.zeros((64, 96, 3), dtype=np.uint8)
    image[:, :] = (10, 20, 30)

    batch = ensure_rgb_batch([image])
    assert batch.shape == (1, DEFAULT_IMAGE_SIZE, DEFAULT_IMAGE_SIZE, 3)
    normalized = normalize_batch_uint8(batch)
    assert normalized.shape == (1, 3, DEFAULT_IMAGE_SIZE, DEFAULT_IMAGE_SIZE)
    assert normalized.dtype == np.float32
