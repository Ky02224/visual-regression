"""Compare two live-eval summaries and say whether the change is worth adopting.

Every change made to this system is justified by an argument and then measured;
more than once the measurement disagreed with the argument. This script makes
that judgement mechanical rather than a matter of eyeballing two numbers: it
prints the pooled delta, the per-class delta, and — when both runs used the same
seeds — a paired per-seed comparison, which is the only honest test available
when the same sites and mutations drive both runs.

A pooled gain smaller than the across-seed spread is noise, and is reported as
noise rather than as a win.

    python scripts/compare_eval_summaries.py \
        --before reports/live-eval-summary.json \
        --after  reports/live-eval-summary-rulefix.json
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--label-before", default="before")
    parser.add_argument("--label-after", default="after")
    args = parser.parse_args()

    before, after = load(ROOT / args.before), load(ROOT / args.after)
    lb, la = args.label_before, args.label_after

    b_acc = float(before["pooled_accuracy"])
    a_acc = float(after["pooled_accuracy"])
    b_n, a_n = int(before["pooled_n"]), int(after["pooled_n"])
    b_c, a_c = int(before["pooled_correct"]), int(after["pooled_correct"])
    delta = a_acc - b_acc

    print(f"{'':<26}{lb:>14}{la:>14}{'delta':>12}")
    print("-" * 66)
    print(f"{'pooled accuracy':<26}{b_acc:>13.2%}{a_acc:>14.2%}{delta:>+12.2%}")
    print(f"{'correct / n':<26}{f'{b_c}/{b_n}':>14}{f'{a_c}/{a_n}':>14}{a_c - b_c:>+12d}")

    spread = max(float(before.get("across_seed_stdev", 0.0)),
                 float(after.get("across_seed_stdev", 0.0)))
    print(f"{'across-seed stdev':<26}{before.get('across_seed_stdev', 0):>14}"
          f"{after.get('across_seed_stdev', 0):>14}")

    # Paired per-seed: same seeds means the same sites and the same mutations,
    # so a per-seed difference isolates the change far better than two pooled
    # numbers, which also absorb whatever the live sites did between runs.
    b_seeds = {s["seed"]: s for s in before.get("per_seed", [])}
    a_seeds = {s["seed"]: s for s in after.get("per_seed", [])}
    shared = sorted(set(b_seeds) & set(a_seeds))
    if shared:
        print(f"\n{'seed':>8}{lb:>12}{la:>12}{'delta':>9}")
        print("-" * 41)
        diffs = []
        for s in shared:
            bc, ac = b_seeds[s]["correct"], a_seeds[s]["correct"]
            diffs.append(ac - bc)
            print(f"{s:>8}{bc:>12}{ac:>12}{ac - bc:>+9d}")
        wins = sum(1 for d in diffs if d > 0)
        losses = sum(1 for d in diffs if d < 0)
        print("-" * 41)
        print(f"{'seeds':>8}{'':>12}{'':>12}{f'{wins}W/{losses}L':>9}")
        if len(diffs) > 1:
            mean_d = statistics.mean(diffs)
            sd = statistics.stdev(diffs)
            print(f"\nper-seed delta: mean {mean_d:+.2f}, sd {sd:.2f}")
            if sd > 0:
                print(f"mean/sd ratio : {mean_d / sd:+.2f}"
                      "  (|ratio| < 1 means the change sits inside the noise)")

    b_cls = before.get("per_class", {})
    a_cls = after.get("per_class", {})
    keys = sorted(set(b_cls) | set(a_cls))
    if keys:
        print(f"\n{'class':<24}{'n':>6}{lb:>12}{la:>12}{'delta':>10}")
        print("-" * 64)
        for k in keys:
            brec, arec = b_cls.get(k, {}), a_cls.get(k, {})
            br, ar = brec.get("recall"), arec.get("recall")
            n = arec.get("n", brec.get("n", 0))
            if br is None or ar is None:
                shown_b = "-" if br is None else f"{br:.0%}"
                shown_a = "-" if ar is None else f"{ar:.0%}"
                print(f"{k:<24}{n:>6}{shown_b:>12}{shown_a:>12}{'':>10}")
                continue
            print(f"{k:<24}{n:>6}{br:>11.0%}{ar:>12.0%}{ar - br:>+10.1%}")

    print("\n=== verdict ===")
    if a_c == b_c:
        print("No change in correct count. Not worth adopting on accuracy grounds.")
    elif a_c < b_c:
        print(f"REGRESSION: {b_c - a_c} fewer correct. Do not adopt.")
    elif abs(delta) < spread:
        print(f"Gain of {delta:+.2%} is smaller than the across-seed spread "
              f"({spread:.2%}). Treat as noise, not an improvement — re-run with "
              "more seeds before adopting.")
    else:
        print(f"Improvement of {delta:+.2%} ({a_c - b_c:+d} samples), larger than the "
              f"across-seed spread ({spread:.2%}). Adoption is justified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
