"""Run live_dom_mutation_eval across several seeds and aggregate the result.

A single 50-trial run is too small to quote on its own: the observed spread
across seeds has been 92-96%, and at n=50 those are not distinguishable. This
driver runs the same evaluation over N seeds and reports the pooled accuracy
with its standard deviation and a normal-approximation 95% interval, so the
headline number comes with an honest error bar.

Per-seed results are kept so an outlier can be inspected rather than averaged
away.

Usage:
    python scripts/live_eval_multiseed.py --seeds 10 --trials 50
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=10, help="How many seeds to run")
    parser.add_argument("--trials", type=int, default=50, help="Trials per seed")
    parser.add_argument("--first-seed", type=int, default=1000)
    parser.add_argument("--out-dir", default="reports/live-eval")
    parser.add_argument("--summary", default="reports/live-eval-summary.json")
    parser.add_argument("--model-path", default=None,
                        help="Evaluate a model other than the deployed one, e.g. a "
                             "candidate from a training workspace.")
    parser.add_argument("--no-dom", action="store_true",
                        help="Withhold the DOM sidecars from every seed — the "
                             "screenshot-only measurement. See live_dom_mutation_eval.py.")
    parser.add_argument("--blind", action="store_true",
                        help="Use the DOM-blind mutation set for every seed — changes "
                             "that repaint the page while leaving the DOM snapshot "
                             "identical. See live_dom_mutation_eval.py.")
    args = parser.parse_args()

    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    seeds = [args.first_seed + i for i in range(args.seeds)]
    per_seed: list[dict] = []

    for index, seed in enumerate(seeds, start=1):
        out_file = out_dir / f"seed-{seed}.json"
        print(f"[{index}/{len(seeds)}] seed={seed} ...", flush=True)
        cmd = [
            sys.executable, str(ROOT / "scripts" / "live_dom_mutation_eval.py"),
            "--trials", str(args.trials),
            "--seed", str(seed),
            "--out", str(out_file),
        ]
        if args.model_path:
            cmd += ["--model-path", args.model_path]
        if args.no_dom:
            cmd += ["--no-dom"]
        if args.blind:
            cmd += ["--blind"]
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not out_file.exists():
            print(f"    FAILED (rc={proc.returncode}): {proc.stderr[-400:]}", flush=True)
            continue
        payload = json.loads(out_file.read_text(encoding="utf-8"))
        results = payload.get("results", [])
        correct = sum(1 for r in results if r.get("correct"))
        per_seed.append({
            "seed": seed,
            "accuracy": payload.get("accuracy"),
            "n": len(results),
            "correct": correct,
        })
        print(f"    accuracy={payload.get('accuracy')}  ({correct}/{len(results)})", flush=True)

    if not per_seed:
        print("No seed completed successfully.")
        return 1

    total_n = sum(s["n"] for s in per_seed)
    total_correct = sum(s["correct"] for s in per_seed)
    pooled = total_correct / total_n
    accuracies = [s["accuracy"] for s in per_seed]
    # Standard deviation across seeds captures run-to-run variation; the
    # binomial standard error captures sampling error at the pooled n. Quote
    # both -- they answer different questions.
    stdev = statistics.stdev(accuracies) if len(accuracies) > 1 else 0.0
    std_err = (pooled * (1 - pooled) / total_n) ** 0.5
    ci_low, ci_high = pooled - 1.96 * std_err, pooled + 1.96 * std_err

    # Per-class recall pooled over every seed, so the small classes are visible
    # rather than hidden inside the headline average.
    expected_counts: Counter[str] = Counter()
    correct_counts: Counter[str] = Counter()
    for seed_info in per_seed:
        payload = json.loads((out_dir / f"seed-{seed_info['seed']}.json").read_text(encoding="utf-8"))
        for row in payload.get("results", []):
            label = row.get("expected_consolidated") or row.get("expected") or "?"
            expected_counts[label] += 1
            if row.get("correct"):
                correct_counts[label] += 1

    print()
    print(f"{'seed':>8}{'n':>6}{'correct':>9}{'accuracy':>10}")
    print("-" * 33)
    for s in per_seed:
        print(f"{s['seed']:>8}{s['n']:>6}{s['correct']:>9}{s['accuracy']:>10.2%}")
    print("-" * 33)
    print(f"{'POOLED':>8}{total_n:>6}{total_correct:>9}{pooled:>10.2%}")
    print()
    print(f"across-seed stdev : {stdev:.4f}")
    print(f"95% CI (binomial) : [{ci_low:.2%}, {ci_high:.2%}]")
    print()
    print(f"{'expected class':<24}{'n':>6}{'recall':>9}")
    print("-" * 39)
    for label in sorted(expected_counts, key=lambda k: -expected_counts[k]):
        n = expected_counts[label]
        print(f"{label:<24}{n:>6}{correct_counts[label] / n:>9.0%}")

    summary = {
        "seeds_run": len(per_seed),
        "trials_per_seed": args.trials,
        "pooled_n": total_n,
        "pooled_correct": total_correct,
        "pooled_accuracy": round(pooled, 4),
        "across_seed_stdev": round(stdev, 4),
        "ci95_low": round(ci_low, 4),
        "ci95_high": round(ci_high, 4),
        "per_seed": per_seed,
        "per_class": {
            label: {"n": expected_counts[label], "recall": round(correct_counts[label] / expected_counts[label], 4)}
            for label in expected_counts
        },
    }
    summary_path = ROOT / args.summary
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nWrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
