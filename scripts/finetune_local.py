"""
Quick fine-tune on an existing visual_ai.pt — no full 9-day retrain needed.

Uses fewer images, fewer epochs, and a lower learning rate. Automatically loads
visual_ai.pt (or visual_ai.ckpt.pt if present) as the starting point.
"""
import logging
import multiprocessing
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# train_model() reports data-loading and per-epoch progress via logger.info(),
# but without a configured handler the logging module silently drops those
# records — every previous run of this script produced a log file with only
# the header below and no visible progress at all, indistinguishable from a
# hang. This makes that progress actually reach stdout/the redirected log.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)

from visual_regression.ai_training import StreamingSyntheticDataset, train_model
from visual_regression.config import WorkspacePaths

StreamingSyntheticDataset._MAX_SRC_PX = 800

MANIFEST = ROOT / ".visual-regression/datasets/public-ui-manifest.json"
MODEL_OUT = ROOT / ".visual-regression/models/visual_ai.pt"
CKPT = MODEL_OUT.with_suffix(".ckpt.pt")

# Fine-tune defaults — much faster than full train_local.py
EPOCHS = 6
SAMPLES_PER_IMAGE = 2
BATCH_SIZE = 16
LEARNING_RATE = 1e-4
MAX_PUBLIC_IMAGES = 300

if __name__ == "__main__":
    multiprocessing.freeze_support()
    paths = WorkspacePaths(root=ROOT / ".visual-regression")
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
    # Forced to CPU below regardless of what's installed — a CUDA-enabled
    # torch build showed up in this environment at some point even though
    # GPU training was explicitly ruled out (MX130's compute capability 5.0
    # is a known risk with modern PyTorch CUDA wheels).
    print(f"  Device   : CPU (forced; CUDA available={torch.cuda.is_available()})")
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
        use_local_baselines=False,
        force_cpu=True,
        include_run_pairs=False,
    )
    elapsed = time.time() - t0
    print(f"\nFine-tune done in {elapsed / 3600:.2f}h")
    print(f"Accuracy: {metadata.get('accuracy', 0):.2%}")
    print(f"Model saved to: {MODEL_OUT}")
