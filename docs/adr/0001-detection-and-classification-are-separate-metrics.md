# ADR 0001 — Detection and classification are reported as separate metrics

**Status:** accepted

## Context

The project has produced four different accuracy numbers, all for the same model
file, and for a while nobody could say which meant what:

| Source | Number | What it actually measured |
|---|---|---|
| `reports/ai-eval-*.json` | 87.6% | Synthetic mutations, n=12,000 — but the calibration temperature was fitted on this same validation set, so it is a validation score, not a test score |
| `scripts/live_dom_mutation_eval.py` | 92–96% | Real third-party pages, injected DOM mutations, n=50 per seed |
| `reports/ai-run-eval-*.json` | 80.7%, later 53.9% | Stored runs, where most "ground truth" labels were the model's own earlier predictions |
| `scripts/benchmark_report.py` | 100% | Whether a change was detected at all — not what it was called |

The 80.7% figure was worse than useless. Its labels came from
`ai_assessment.label` on runs that had never been reviewed by a human, so it
scored the model against its own past output. Removing the train/eval
contamination dropped it to 53.9%, which reads as a catastrophic result and is
actually just a measurement of noise.

## Decision

Report **detection** and **classification** as two metrics, never combined, and
name the evaluation set for each.

- **Detection**: share of injected defects flagged, plus the control group's
  false-alarm rate. Ground truth is the defect mode encoded in the case name.
- **Classification**: accuracy on `live_dom_mutation_eval` pooled across seeds,
  with a confidence interval. Ground truth is the mutation the script injected.

The run-based evaluation is retired as a headline number. It stays in the code
because it is still useful for spotting drift against production data, but its
labels are not trustworthy enough to publish.

## Consequences

- The published figures are **detection 81/81 with 0/9 false alarms**, and
  **classification 94.20% (n=500, 95% CI [92.15%, 96.25%], across-seed σ 2.39%)**.
- The synthetic 87.6% is reported as a *validation* score with the calibration
  caveat stated, not as a test result.
- Anyone adding an evaluation must state its ground-truth source. An evaluation
  whose labels come from the model is not an evaluation.
- `scripts/live_eval_multiseed.py` exists so the headline number can be
  reproduced with an error bar rather than quoted from a single lucky seed.
