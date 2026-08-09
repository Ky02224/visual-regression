"""Measure a checkpoint's noise-override confidence and write it into the file.

The threshold above which the model's own verdict outranks the pixel-noise
rules is a property of that model's confidence distribution, and using another
model's number is what broke the no-DOM path: the hand-set 0.80 came from a
model whose unchanged pages topped out at 0.729, while a later model's *real
defects* peaked at 0.756, so the exemption never fired and 36.9% of an exam was
reported as "no change".

train_model calibrates this during its final validation pass, but that pass is
built from synthetic base images only. Training on real pairs alone
(``--max-public-images 0``) leaves it with too few unchanged samples to locate a
99th percentile, so it keeps the hand-set default — which is exactly the value
that is wrong for such a model. This script does the measurement the way it
should be done for those runs: against real unchanged pairs.

Usage:
    python scripts/calibrate_noise_override.py MODEL.pt --manifest MANIFEST.json
    python scripts/calibrate_noise_override.py MODEL.pt --manifest M.json --dry-run
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import numpy as np
import torch

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from visual_regression.ai_training import (  # noqa: E402
    _NOISE_OVERRIDE_CONFIDENCE,
    assess_results_batch,
)
from visual_regression.image_compare import compare_arrays  # noqa: E402

BENIGN_LABELS = {"benign", "insignificant-change", "no-change"}


def _compare(baseline_path: str, current_path: str):
    import cv2

    a, b = cv2.imread(baseline_path), cv2.imread(current_path)
    if a is None or b is None:
        return None
    out = compare_arrays(a, b, 30, 120, [])
    return out[0] if isinstance(out, tuple) else out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("model", type=pathlib.Path)
    ap.add_argument("--manifest", type=pathlib.Path, required=True)
    ap.add_argument("--max-pairs", type=int, default=120)
    ap.add_argument("--percentile", type=float, default=99.0)
    ap.add_argument("--margin", type=float, default=0.02)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--dry-run", action="store_true",
                    help="report the value without writing it into the checkpoint")
    args = ap.parse_args()

    if not args.model.exists():
        print(f"no checkpoint at {args.model}")
        return 1

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    benign = [p for p in manifest.get("pairs", []) if p.get("label") in BENIGN_LABELS]
    if len(benign) < 30:
        print(f"only {len(benign)} unchanged pairs in the manifest; refusing to "
              f"calibrate on fewer than 30 — a ceiling read off a handful of "
              f"points is worse than the default it would replace")
        return 1
    benign = benign[: args.max_pairs]

    batch = []
    for p in benign:
        result = _compare(p["baseline"], p["current"])
        if result is None:
            continue
        batch.append({
            "result": result,
            "baseline_image_path": pathlib.Path(p["baseline"]),
            "current_image_path": pathlib.Path(p["current"]),
        })
    print(f"scoring {len(batch)} unchanged pairs on {args.device} ...")
    if len(batch) < 30:
        print(f"only {len(batch)} pairs were readable; refusing to calibrate")
        return 1

    assessments = assess_results_batch(batch, args.model, device=args.device)
    scores = np.array([float(a.get("ai_score") or 0.0) for a in assessments], dtype=np.float64)

    ceiling = float(np.percentile(scores, args.percentile)) + args.margin
    value = float(min(0.90, max(0.20, ceiling)))

    print(f"\nunchanged-page confidence: median {np.median(scores):.4f}  "
          f"p{args.percentile:g} {np.percentile(scores, args.percentile):.4f}  max {scores.max():.4f}")
    print(f"calibrated noise-override: {value:.4f}   (was {_NOISE_OVERRIDE_CONFIDENCE:.2f})")

    if args.dry_run:
        print("dry run — checkpoint not modified")
        return 0

    ckpt = torch.load(args.model, map_location="cpu", weights_only=False)
    if not isinstance(ckpt, dict):
        print("checkpoint is not a dict; refusing to modify it")
        return 1
    previous = ckpt.get("noise_override_confidence")
    ckpt["noise_override_confidence"] = value
    torch.save(ckpt, args.model)
    print(f"wrote noise_override_confidence={value:.4f} into {args.model} (was {previous})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
