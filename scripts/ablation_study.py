"""Measure what each information source contributes, by removing one at a time.

The headline accuracy is produced by four sources working together: a
deterministic DOM structure comparison, 53 DOM-derived feature columns, 15
pixel-structural columns, and a ResNet50 Siamese embedding of the two crops.
A single number cannot say which of them is carrying the result, and the
existing --no-dom run cannot either: withholding the sidecar removes the
structural verdict *and* 53 of the 77 feature columns at once, so the drop it
produces is unattributable.

Each configuration below runs the same trials — same seeds, same sites, same
mutations — with exactly one thing removed, so the difference from the full
system is that thing's contribution.

    python scripts/ablation_study.py --seeds 3 --trials 50

Runs are sequential on purpose: two Playwright browsers driving live sites at
once distort each other's timing, and these captures are already sensitive
enough to it that the harness waits on document.fonts.ready twice.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# name -> (env overrides, extra CLI args, what the number means)
CONFIGURATIONS: dict[str, tuple[dict[str, str], list[str], str]] = {
    "full": (
        {},
        [],
        "Everything on. The published figure.",
    ),
    "no-dom-engine": (
        {"LENS_ABLATE_DOM_ENGINE": "true"},
        [],
        "Structural verdict computed and discarded; the network and the vetoes "
        "decide, with the DOM feature columns still populated. The gap to full "
        "is the rule engine's contribution.",
    ),
    "no-dom-features": (
        {"LENS_ABLATE_DOM_FEATURES": "true"},
        [],
        "The 53 DOM columns neutralised, rule engine still deciding. Isolates "
        "how much the network was using DOM evidence directly.",
    ),
    "no-pixel-features": (
        {"LENS_ABLATE_PIXEL_FEATURES": "true"},
        [],
        "The 15 pixel-structural columns neutralised. These were the ones "
        "found to be zero-padded at inference for four model revisions.",
    ),
    "no-dom-at-all": (
        {"LENS_ABLATE_DOM_ENGINE": "true", "LENS_ABLATE_DOM_FEATURES": "true"},
        ["--no-dom"],
        "Screenshot-only: no sidecar, no verdict, no DOM columns. What a "
        "client that uploads pixels alone gets.",
    ),
    "blind-mutations": (
        {},
        ["--blind"],
        "Full system, but on mutations that repaint the page while leaving the "
        "DOM snapshot identical. The rule engine has nothing to match on, so "
        "the accuracy here belongs to the visual stream.",
    ),
}


def run_configuration(name: str, seeds: int, trials: int, first_seed: int,
                      model_path: str | None) -> dict:
    env_overrides, extra_args, _description = CONFIGURATIONS[name]
    out_dir = ROOT / "reports" / f"ablation-{name}"
    summary = ROOT / "reports" / f"ablation-summary-{name}.json"

    cmd = [
        sys.executable, str(ROOT / "scripts" / "live_eval_multiseed.py"),
        "--seeds", str(seeds),
        "--trials", str(trials),
        "--first-seed", str(first_seed),
        "--out-dir", str(out_dir.relative_to(ROOT)),
        "--summary", str(summary.relative_to(ROOT)),
    ] + extra_args
    if model_path:
        cmd += ["--model-path", model_path]

    env = dict(os.environ)
    env.update(env_overrides)
    # Inference goes through the in-process path rather than the microservice,
    # which would not see these switches at all.
    env["VRT_DISABLE_AI_SPLIT"] = "true"

    flags = " ".join(f"{k}={v}" for k, v in env_overrides.items()) or "(none)"
    print(f"\n=== {name} ===\n    switches: {flags}", flush=True)

    proc = subprocess.run(cmd, cwd=str(ROOT), env=env)
    if proc.returncode != 0 or not summary.exists():
        print(f"    FAILED (rc={proc.returncode})", flush=True)
        return {"config": name, "error": True}

    payload = json.loads(summary.read_text(encoding="utf-8"))
    return {
        "config": name,
        "pooled_accuracy": payload.get("pooled_accuracy"),
        "pooled_correct": payload.get("pooled_correct"),
        "pooled_n": payload.get("pooled_n"),
        "ci95_low": payload.get("ci95_low"),
        "ci95_high": payload.get("ci95_high"),
        "per_class": payload.get("per_class"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--trials", type=int, default=50)
    parser.add_argument("--first-seed", type=int, default=1000)
    parser.add_argument("--model-path", default=None)
    parser.add_argument("--only", nargs="*", choices=sorted(CONFIGURATIONS),
                        help="Run a subset. Defaults to all of them.")
    parser.add_argument("--out", default="reports/ablation-study.json")
    args = parser.parse_args()

    names = args.only or list(CONFIGURATIONS)
    rows = [run_configuration(n, args.seeds, args.trials, args.first_seed, args.model_path)
            for n in names]

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "seeds": args.seeds,
        "trials_per_seed": args.trials,
        "first_seed": args.first_seed,
        "configurations": rows,
    }, indent=2), encoding="utf-8")

    full = next((r for r in rows if r.get("config") == "full"), None)
    baseline = full.get("pooled_accuracy") if full and not full.get("error") else None

    print("\n" + "=" * 78)
    print(f"{'configuration':20s} {'accuracy':>10s} {'vs full':>10s}   n")
    print("-" * 78)
    for row in rows:
        if row.get("error"):
            print(f"{row['config']:20s} {'FAILED':>10s}")
            continue
        accuracy = row["pooled_accuracy"]
        delta = f"{(accuracy - baseline) * 100:+.2f}pp" if baseline is not None else "-"
        if row["config"] == "full":
            delta = "-"
        print(f"{row['config']:20s} {accuracy:>9.2%} {delta:>10s}   {row['pooled_n']}")
    print("=" * 78)
    print(f"\nSaved to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
