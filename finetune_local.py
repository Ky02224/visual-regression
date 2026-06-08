"""
Quick fine-tune on an existing visual_ai.pt — no full 9-day retrain needed.

Uses fewer images, fewer epochs, and a lower learning rate. Automatically loads
visual_ai.pt (or visual_ai.ckpt.pt if present) as the starting point.
"""
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

# Fine-tune defaults — much faster than full train_local.py
EPOCHS = 12
SAMPLES_PER_IMAGE = 4
BATCH_SIZE = 16
LEARNING_RATE = 1e-4
MAX_PUBLIC_IMAGES = 1500

if __name__ == "__main__":
    multiprocessing.freeze_support()
    paths = WorkspacePaths(ROOT)
    paths.ensure()
    MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)

    if not MODEL_OUT.exists() and not CKPT.exists():
        print("ERROR: No existing model found.")
        print(f"  Expected: {MODEL_OUT}")
        print(f"  Or checkpoint: {CKPT}")
        print("Copy your trained visual_ai.pt into .visual-regression/models/ first.")
        sys.exit(1)

    if not MANIFEST.exists():
        print("ERROR: Dataset manifest missing. Run: python download_datasets.py")
        sys.exit(1)

    import torch

    resume = "checkpoint" if CKPT.exists() else "model weights"
    print("=" * 55)
    print("  Visual Regression AI — Fine-tune (quick)")
    print(f"  Device   : {'CUDA - ' + torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")
    print(f"  Source   : {resume}")
    print(f"  Epochs   : {EPOCHS}  |  LR: {LEARNING_RATE}")
    print(f"  Images   : up to {MAX_PUBLIC_IMAGES} (not full 9000)")
    print("=" * 55)

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
        max_public_images=MAX_PUBLIC_IMAGES,
    )
    elapsed = time.time() - t0
    print(f"\nFine-tune done in {elapsed / 3600:.2f}h")
    print(f"Accuracy: {metadata.get('accuracy', 0):.2%}")
    print(f"Model saved to: {MODEL_OUT}")
