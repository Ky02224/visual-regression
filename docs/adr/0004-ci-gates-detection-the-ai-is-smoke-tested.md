# ADR 0004 — CI gates on detection; the AI is smoke-tested, not measured

**Status:** accepted

## Context

The model is large — 304MB checkpoint, 124MB `.pt`, 32MB quantised ONNX — and
getting it into CI needs a distribution decision. The obvious framing was "the
AI must run in CI or the project cannot claim to be AI-based", which conflates
two different things:

- **What the product is.** The AI runs on every real comparison: the dashboard,
  `--comparison-mode ai`, and every screenshot the SDK submits. That is what
  makes it AI-based, regardless of what a test harness does.
- **What CI proves.** A CI run of the model proves it loads and emits output. It
  does not measure accuracy — that needs a labelled evaluation set, which
  already exists and is far more rigorous than a smoke test.

The benchmark was run twice, with and without the model, to find out what CI
actually depends on:

| | with model | with `--no-ai` |
|---|---|---|
| Defects detected | 81/81 | **81/81** |
| Control false alarms | 0/9 | 0/9 |
| AI label correct | 46/81 | **0/81** |
| `decision_source` | `ai` | `pixel-fallback-no-model` |

Detection is pixel arithmetic. The smallest injected defect produces a 2.81%
mismatch against a 0.25% threshold — eleven times over — so the model changes
nothing about whether a regression is caught. Classification depends on it
entirely.

## Decision

Split the two capabilities across two mechanisms.

**CI gates on detection.** `scripts/benchmark_report.py` fails the build on any
missed defect or control-group false alarm. This runs without the model, so it
is never blocked on model distribution and never flaky because of it.

**CI smoke-tests the AI path.** A separate job restores the 32MB quantised ONNX
via Git LFS and asserts `decision_source` is not `pixel-fallback-no-model` — so
"the AI executed in CI" is a checked claim rather than an assumption.

**Classification accuracy is measured offline.** `scripts/live_eval_multiseed.py`
against real third-party pages, with the summary committed to
`reports/live-eval-summary.json`. This does not belong in CI: it depends on
external sites being reachable, which would make the pipeline slow and flaky for
a number that does not change between commits.

## Consequences

- The published claims map onto how each is verified:
  - *Detection*: 81/81, 0/9 false alarms — enforced by a CI gate on every push.
  - *AI path*: executed in CI, asserted via `decision_source`.
  - *Classification*: 94.20%, n=500, 95% CI [92.15%, 96.25%] — measured offline.
- Git LFS carries 32MB. The free tier allows roughly 31 CI restores per month,
  which suits this project's push volume. If that becomes tight, the smoke job
  can move to a schedule without touching the detection gate.
- The `::warning::` the tool already emits when no model is present
  (`the AI did not run for it`) stays. It was written before this decision and
  turned out to be exactly the right signal — the run above confirms it fires
  correctly.
- A future change that makes detection depend on the model would break this
  split. The `--no-ai` benchmark run is the check for that.
