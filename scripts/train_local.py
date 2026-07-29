"""
Local training script for Visual Regression AI.
Optimized for 16GB RAM + MX130 2GB VRAM.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from visual_regression.ai_training import train_model, StreamingSyntheticDataset
from visual_regression.config import WorkspacePaths

# OOM prevention: 5000 images x 600px x 2 copies = ~7GB < 16GB RAM
StreamingSyntheticDataset._MAX_SRC_PX = 800

MANIFEST = ROOT / ".visual-regression/datasets/public-ui-manifest.json"
MODEL_OUT = ROOT / ".visual-regression/models/visual_ai.pt"
MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)

EPOCHS = 20
SAMPLES_PER_IMAGE = 4
BATCH_SIZE = 16
LEARNING_RATE = 3e-4

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()

    paths = WorkspacePaths(root=ROOT / ".visual-regression")
    paths.ensure()

    import torch
    print("=" * 55)
    print("  Visual Regression AI Training (Local)")
    print(f"  Device  : {'CUDA - ' + torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
    print(f"  Epochs  : {EPOCHS}  |  Samples: {SAMPLES_PER_IMAGE}/image")
    print(f"  Max px  : {StreamingSyntheticDataset._MAX_SRC_PX}  |  Batch: {BATCH_SIZE}")
    print(f"  Manifest: {'✅ Found' if MANIFEST.exists() else '❌ Run download_datasets.py first!'}")
    print("=" * 55)

    if not MANIFEST.exists():
        print("\nERROR: Dataset not found. Run this first:")
        print("  python download_datasets.py")
        sys.exit(1)

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
    elapsed = time.time() - t0
    print(f"\nTraining done! {elapsed/3600:.1f}h")
    print(f"Accuracy: {metadata['accuracy']:.2%}")
    print(f"Model saved to: {MODEL_OUT}")
