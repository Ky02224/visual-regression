"""Fine-tune the classifier on browser-rendered mutation pairs.

The shipped model learned from dataset_generator.py's OpenCV edits — a filled
rectangle for a removed element, an HSV shift for a colour regression. Measured
2026-08-05: 87.6% on that synthetic validation set, 22.2% on real pages, with
broken-image, font-change and text-issue at 0%. The pairs produced by
generate_live_training_pairs.py are the same defect categories as actually
rendered by a browser, reflow and all.

Nothing here overwrites the deployed model. Training runs inside its own
workspace root and writes visual_ai_live.pt; .visual-regression/models/
visual_ai.pt is never opened for writing, so the current 94.2% pipeline and
every committed result stay valid whatever this produces. The new model is worth
adopting only if it beats the old one on the same protocol — that comparison is
a separate step, deliberately.

train_model() consumes real pairs through `_load_run_pair_samples`, which reads
run directories, so the manifest is materialised into that shape first. It also
resumes from `<model_path>.ckpt.pt`, so seeding that file with the current
checkpoint makes this a fine-tune rather than a fresh start.

    python scripts/finetune_on_live_pairs.py --epochs 4
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from visual_regression.ai_training import train_model  # noqa: E402
from visual_regression.config import WorkspacePaths  # noqa: E402

BENIGN_CATEGORIES = {"benign", "no-change", "insignificant-change"}


def _link_or_copy(src: Path, dst: Path) -> None:
    """Hardlink where the filesystem allows it; ~5k screenshots is ~1GB copied."""
    if dst.exists():
        return
    try:
        os.link(src, dst)
    except Exception:
        shutil.copyfile(src, dst)


def materialise_runs(manifest_path: Path, runs_dir: Path) -> dict:
    """Turn generated pairs into the run-directory layout the loader expects.

    A defect pair is written as a rejected FAIL carrying its ground-truth label;
    a benign pair as a PASS. Those are the two shapes `_load_run_pair_samples`
    maps to a label without falling back to its own heuristic guess, which would
    silently relabel the data we went to the trouble of capturing.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pairs = manifest["pairs"]
    runs_dir.mkdir(parents=True, exist_ok=True)

    written, skipped = 0, 0
    for i, rec in enumerate(pairs):
        baseline_src, current_src = Path(rec["baseline"]), Path(rec["current"])
        if not baseline_src.is_file() or not current_src.is_file():
            skipped += 1
            continue

        label = rec["label"]
        benign = label in BENIGN_CATEGORIES
        # The name seeds _run_pair_split's hash, so the 80/20 train/eval split is
        # stable across re-runs and no pair is ever both trained and scored on.
        run_dir = runs_dir / f"live-{i:05d}_{label}"
        run_dir.mkdir(exist_ok=True)

        _link_or_copy(baseline_src, run_dir / "baseline.png")
        _link_or_copy(current_src, run_dir / "current.png")
        for side, src in (("baseline", baseline_src), ("current", current_src)):
            dom_src = src.with_suffix(".dom.json")
            if dom_src.is_file():
                _link_or_copy(dom_src, run_dir / f"{side}.dom.json")

        payload = {
            "status": "PASS" if benign else "FAIL",
            "decision": {"status": "pending" if benign else "rejected"},
            "ai_assessment": {} if benign else {"label": label},
            "result": {},
            "url": rec.get("url", ""),
        }
        (run_dir / "result.json").write_text(json.dumps(payload), encoding="utf-8")
        written += 1

    return {"written": written, "skipped": skipped, "total": len(pairs)}


def main() -> int:
    # Without this every logger.info in the training path is dropped: no handler
    # is configured, so Python's last-resort handler emits WARNING and above and
    # nothing else. Everything the run tries to report about itself went to
    # nowhere — the validation split size, the resumed epoch, the temperature and
    # noise-override calibration, the partial-checkpoint warning, and the
    # per-epoch per-class recall. Six training runs were judged on a progress bar
    # and a final number because of it, and three of them were diagnosed hours
    # late for want of a line the code was already writing.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest",
                        default=".visual-regression/datasets/live-training-pairs/manifest.json")
    parser.add_argument("--workspace", default=".visual-regression-train")
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=5e-5,
                        help="Below the 1e-4 used for the original run: this starts "
                             "from trained weights, so large steps would discard them.")
    # The real pairs are the point of this run, so the synthetic side is kept
    # small — enough to limit forgetting, not enough to drown the new data.
    parser.add_argument("--max-public-images", type=int, default=150)
    parser.add_argument("--samples-per-image", type=int, default=4)
    parser.add_argument("--run-pair-oversample", type=int, default=2,
                        help="The 15x default exists for workspaces holding a handful "
                             "of real runs; with thousands, repetition just wastes epochs.")
    parser.add_argument("--boost-class", action="append", default=[], metavar="NAME=FACTOR",
                        help="Multiply a class's loss weight, e.g. --boost-class color-regression=4. "
                             "The corpus is balanced by construction, so inverse-frequency weighting "
                             "treats a class the model gets right 5%% of the time exactly like one it "
                             "gets right 100%% of the time; this is how to say which are actually hard.")
    parser.add_argument("--dom-dropout", type=float, default=0.0,
                        help="Fraction of training samples whose DOM+structural feature "
                             "block is zeroed, so the image streams learn to classify "
                             "without DOM — the screenshot-only inference case. 0 keeps "
                             "the previous behaviour.")
    parser.add_argument("--image-dropout", type=float, default=0.0,
                        help="Fraction of training samples whose image streams are "
                             "zeroed, so the head must classify from the feature "
                             "vector. The images encode change magnitude, which "
                             "reproduces 83.2%% of the model's predictions and cannot "
                             "separate layout-issue, text-issue, broken-image and "
                             "font-change from one another; removing it on some "
                             "samples is what forces the rest of the evidence to be "
                             "used. 0 keeps the previous behaviour.")
    parser.add_argument("--min-pairs", type=int, default=50,
                        help="Refuse to train on fewer than this many pairs. Lower it "
                             "only to smoke-test the pipeline end to end.")
    args = parser.parse_args()

    manifest_path = ROOT / args.manifest
    if not manifest_path.is_file():
        print(f"No manifest at {manifest_path} — run generate_live_training_pairs.py first.")
        return 1

    ws_root = ROOT / args.workspace
    paths = WorkspacePaths(root=ws_root)
    paths.ensure()

    stats = materialise_runs(manifest_path, paths.runs_dir)
    print(f"Materialised {stats['written']} run dirs "
          f"({stats['skipped']} skipped of {stats['total']}).")
    if stats["written"] < args.min_pairs:
        print(f"Only {stats['written']} usable pairs, below --min-pairs "
              f"({args.min_pairs}); stopping.")
        return 1

    model_path = paths.models_dir / "visual_ai_live.pt"
    models_root = ROOT / ".visual-regression" / "models"
    source_ckpt = models_root / "visual_ai.ckpt.pt"
    source_meta = models_root / "visual_ai.json"
    target_ckpt = model_path.with_suffix(".ckpt.pt")

    if source_ckpt.is_file() and not target_ckpt.exists():
        print(f"Seeding checkpoint from {source_ckpt.name} (fine-tune, not fresh training).")
        shutil.copyfile(source_ckpt, target_ckpt)
    elif not source_ckpt.is_file():
        print("WARNING: no existing checkpoint found — this will train from ImageNet weights.")

    # The deployed model's class order is NOT CONSOLIDATED_CLASS_NAMES: it runs
    # insignificant-change, missing-element, layout-issue, text-issue, ... while
    # the constant runs insignificant-change, layout-issue, text-issue,
    # missing-element, ... — three classes apart. Inference is safe because it
    # reads the order back from the model file, but train_model() only falls back
    # to those files when the checkpoint itself carries no "class_names", and
    # this checkpoint carries none. Without the metadata beside it, training
    # would resolve to the constant and teach the pretrained head that its
    # missing-element output means layout-issue — scrambled targets, silently.
    if source_meta.is_file():
        for meta_target in (target_ckpt.with_suffix(".json"), model_path.with_suffix(".json")):
            if not meta_target.exists():
                shutil.copyfile(source_meta, meta_target)
        expected = json.loads(source_meta.read_text(encoding="utf-8")).get("class_names")
        resolved = json.loads(target_ckpt.with_suffix(".json").read_text(
            encoding="utf-8")).get("class_names")
        if expected != resolved:
            print("Class order mismatch after seeding metadata; refusing to train.")
            return 1
        print(f"Class order pinned to the checkpoint's own: {resolved}")
    else:
        print("WARNING: no visual_ai.json beside the checkpoint — cannot verify class order.")

    print(f"Training -> {model_path}")
    print("The deployed .visual-regression/models/visual_ai.pt is not touched.")

    summary = train_model(
        paths=paths,
        model_path=model_path,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        samples_per_image=args.samples_per_image,
        dataset_manifest_path=ROOT / ".visual-regression" / "datasets" / "public-ui-manifest.json",
        max_public_images=args.max_public_images,
        use_local_baselines=False,
        include_run_pairs=True,
        run_pair_oversample=args.run_pair_oversample,
        dom_dropout=args.dom_dropout,
        image_dropout=args.image_dropout,
        class_difficulty={k: float(v) for k, v in
                          (spec.split("=", 1) for spec in args.boost_class)} or None,
    )

    print("\n=== training summary ===")
    for key in ("accuracy", "samples", "epochs", "model_path"):
        if key in summary:
            print(f"  {key}: {summary[key]}")
    print("\nNext: evaluate this model against the current one on the same protocol "
          "before adopting it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
