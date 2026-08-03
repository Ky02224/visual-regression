"""Score a benchmark suite run: how many injected defects did the tool actually catch?

Reads the runs written by `run-suite --suite suites/suite.benchmark.yaml` and
reports, per injected defect mode:

  * detection rate  — share of defective cases the tool flagged (status FAIL).
                      This is recall on known-bad input.
  * false alarms    — control cases (`-none`, clean vs clean) that were flagged
                      anyway. This is the false-positive rate.
  * AI label accuracy — of the defects that WERE caught, how often the AI named
                      the right change type. Scored only on caught cases, since a
                      missed defect has no label to judge.

Ground truth comes from the case name, which encodes the injected mode — not from
the AI's own output, so this is a genuine external benchmark rather than the
self-labelled run data that `evaluate-ai --on-runs` scores against.

Exits non-zero if any injected defect went undetected, so CI can gate on it.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

# Injected mode (from the demo portal's ?defect= values) -> the consolidated
# class the AI is expected to report. Several raw modes fold into one class:
# the model is trained on the consolidated 7-class space, not the raw modes.
#
# CAVEAT for anyone quoting the label column: this mapping is a judgement, and
# one row is genuinely arguable. `unreadable-text` only sets `color:` on two
# headings (see .unreadable-text in demo_portal/styles.css), so what actually
# changes on screen IS a colour. Scored against "text-issue" the model gets 0/9;
# scored against "color-regression" it gets 9/9, because it answers
# color-regression every single time — consistent, not confused. The detection
# rate above is unaffected either way; only the label column moves. It is left
# as text-issue here because the defect's INTENT is a readability failure, but
# the number should be reported with that ambiguity stated rather than as a
# clean model error.
MODE_TO_EXPECTED_CLASS = {
    "missing-cta": "missing-element",
    "shift-card": "layout-issue",
    "misaligned-fields": "layout-issue",
    "overlay-obstruction": "layout-issue",
    "z-index-issue": "layout-issue",
    "text-truncation": "text-issue",
    "unreadable-text": "text-issue",
    "broken-image": "broken-image",
    "theme-shift": "color-regression",
}

CASE_RE = re.compile(r"_(bmk-\d+)-(index|login|dashboard)-([\w-]+?)-(" + "|".join(
    list(MODE_TO_EXPECTED_CLASS) + ["none"]
) + r")_")


def collect(runs_dir: Path) -> list[dict]:
    """Return the most recent run per benchmark case name."""
    latest: dict[str, tuple[str, dict]] = {}
    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        match = CASE_RE.search(run_dir.name)
        if not match:
            continue
        result_file = run_dir / "result.json"
        if not result_file.exists():
            continue
        try:
            payload = json.loads(result_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        case_id, page, locale, mode = match.groups()
        key = f"{case_id}-{page}-{locale}-{mode}"
        # Directory names start with a sortable timestamp, so the last one wins.
        if key not in latest or run_dir.name > latest[key][0]:
            latest[key] = (
                run_dir.name,
                {
                    "mode": mode,
                    "page": page,
                    "locale": locale,
                    "status": str(payload.get("status") or "").upper(),
                    "mismatch_pct": (payload.get("result") or {}).get("mismatch_pct"),
                    "ai_label": (payload.get("ai_assessment") or {}).get("label") or "",
                    "decision_source": (payload.get("comparison_decision") or {}).get("decision_source", ""),
                },
            )
    return [entry for _, entry in latest.values()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".visual-regression")
    parser.add_argument("--json-out", default=None, help="Also write the summary as JSON")
    parser.add_argument(
        "--suite",
        default="suites/suite.benchmark.yaml",
        help="Suite the runs came from; used to verify every case actually reported",
    )
    args = parser.parse_args()

    runs_dir = Path(args.workspace) / "runs"
    if not runs_dir.exists():
        print(f"No runs directory at {runs_dir}")
        return 2

    entries = collect(runs_dir)
    if not entries:
        print("No benchmark runs found. Run:")
        print("  python -m visual_regression.cli create-suite-baselines --suite suites/suite.benchmark.yaml --overwrite")
        print("  python -m visual_regression.cli run-suite --suite suites/suite.benchmark.yaml")
        return 2

    # A half-finished suite would otherwise report "100% detected" off whatever
    # handful of cases happened to write a result.json — the most flattering and
    # most wrong number this script could produce.
    expected_cases = 0
    suite_path = Path(args.suite)
    if suite_path.exists():
        try:
            import yaml

            suite = yaml.safe_load(suite_path.read_text(encoding="utf-8")) or {}
            expected_cases = len(suite.get("tests") or [])
        except Exception as exc:
            print(f"Could not read {suite_path} to check completeness: {exc}")

    per_mode: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        per_mode[entry["mode"]].append(entry)

    controls = per_mode.pop("none", [])
    false_alarms = [e for e in controls if e["status"] == "FAIL"]

    print(f"{'injected defect':<22}{'cases':>7}{'detected':>10}{'recall':>9}{'AI label ok':>13}")
    print("-" * 61)

    total = detected = labelled_ok = 0
    rows = {}
    for mode in sorted(per_mode):
        cases = per_mode[mode]
        caught = [e for e in cases if e["status"] == "FAIL"]
        expected = MODE_TO_EXPECTED_CLASS[mode]
        correct = [e for e in caught if e["ai_label"] == expected]
        total += len(cases)
        detected += len(caught)
        labelled_ok += len(correct)
        label_col = f"{len(correct)}/{len(caught)}" if caught else "-"
        print(
            f"{mode:<22}{len(cases):>7}{len(caught):>10}{len(caught) / len(cases):>8.0%}{label_col:>13}"
        )
        rows[mode] = {
            "cases": len(cases),
            "detected": len(caught),
            "recall": round(len(caught) / len(cases), 4),
            "expected_class": expected,
            "ai_label_correct": len(correct),
        }

    print("-" * 61)
    print(f"{'ALL INJECTED DEFECTS':<22}{total:>7}{detected:>10}{detected / total:>8.0%}"
          f"{f'{labelled_ok}/{detected}' if detected else '-':>13}")
    print()
    print(f"Control cases (clean vs clean): {len(controls)}  false alarms: {len(false_alarms)}")
    if controls:
        print(f"False-positive rate: {len(false_alarms) / len(controls):.0%}")

    sources = {e["decision_source"] for e in entries if e["decision_source"]}
    if sources:
        print(f"Decision sources seen: {', '.join(sorted(sources))}")
    if any("no-model" in s for s in sources):
        print("WARNING: at least one case fell back to pixel comparison — the AI did not run for it.")

    summary = {
        "total_injected": total,
        "detected": detected,
        "detection_rate": round(detected / total, 4) if total else 0.0,
        "ai_label_correct": labelled_ok,
        "ai_label_accuracy_on_detected": round(labelled_ok / detected, 4) if detected else 0.0,
        "control_cases": len(controls),
        "false_alarms": len(false_alarms),
        "false_positive_rate": round(len(false_alarms) / len(controls), 4) if controls else 0.0,
        "per_mode": rows,
        "decision_sources": sorted(sources),
    }
    if args.json_out:
        out_path = Path(args.json_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"\nWrote {out_path}")

    if expected_cases and len(entries) < expected_cases:
        print(
            f"\nFAIL: only {len(entries)} of {expected_cases} suite cases reported a result. "
            "The rates above are computed off a partial run and cannot be trusted."
        )
        return 1

    missed = total - detected
    if missed:
        print(f"\nFAIL: {missed} injected defect(s) went undetected.")
        return 1
    if false_alarms:
        print(f"\nFAIL: {len(false_alarms)} control case(s) raised a false alarm.")
        return 1
    print("\nOK: every injected defect was detected and no control case false-alarmed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
