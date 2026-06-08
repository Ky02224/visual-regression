"""Retrain visual_ai.pt with 8 defect classes (no insignificant-change)."""
from __future__ import annotations

import multiprocessing
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from visual_regression.ai_training import StreamingSyntheticDataset, train_model
from visual_regression.config import WorkspacePaths

StreamingSyntheticDataset._MAX_SRC_PX = 800

MANIFEST = ROOT / ".visual-regression/datasets/public-ui-manifest.json"
MODEL_OUT = ROOT / ".visual-regression/models/visual_ai.pt"
CKPT = MODEL_OUT.with_suffix(".ckpt.pt")

EPOCHS = 20
SAMPLES_PER_IMAGE = 4
BATCH_SIZE = 16
LEARNING_RATE = 3e-4


if __name__ == "__main__":
    multiprocessing.freeze_support()
    paths = WorkspacePaths(ROOT)
    paths.ensure()
    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)

    if CKPT.exists():
        print(f"Removing incompatible checkpoint: {CKPT}")
        CKPT.unlink()

    if not MANIFEST.exists():
        print("Dataset manifest missing. Run: python download_datasets.py")
        sys.exit(1)

    import torch

    print("Retraining 8-class visual_ai.pt …")
    print(f"Device: {'CUDA' if torch.cuda.is_available() else 'CPU'}")
    t0 = time.time()
    metadata = train_model(
        paths=paths,
        model_path=MODEL_OUT,
        epochs=EPOCHS,
        batch_size=BATCH_SIZE,
        learning_rate=LEARNING_RATE,
        samples_per_image=SAMPLES_PER_IMAGE,
        pixel_threshold=20,
        min_region_area=120,
        pretrained_backbone=True,
        dataset_manifest_path=MANIFEST,
        max_public_images=9000,
    )
    print(f"Done in {(time.time() - t0) / 3600:.2f}h — accuracy {metadata.get('accuracy', 0):.2%}")
    print(f"Saved: {MODEL_OUT}")
