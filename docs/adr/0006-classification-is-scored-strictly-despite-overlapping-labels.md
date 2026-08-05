# 0006 — Classification is scored strictly, despite overlapping labels

## Status

Accepted, 2026-08-05.

## Context

Classification is reported as 94.20% (471/500, `reports/live-eval-summary.json`).
Grouping the 29 residual errors by which pair of labels they fall between shows
they are not spread across the class set:

```
  7  missing-element   -> layout-issue
  6  missing-element   -> broken-image
  4  missing-element   -> color-regression
  4  layout-issue      -> text-issue
  4  text-issue        -> layout-issue
  2  text-issue        -> missing-element
  1  font-change       -> missing-element
  1  color-regression  -> insignificant-change
```

Twenty-one of the twenty-nine sit between three pairs that describe the same
event from different angles:

- **missing-element / layout-issue** — removing an element reflows everything
  below it. The removal and the shift are one event.
- **text-issue / layout-issue** — text that overflows or clips has, by
  definition, changed the layout around it.
- **missing-element / broken-image** — an image that vanished is both.

Treating those three pairs as interchangeable gives 98.40% (492/500) on exactly
the same run.

This also explains three failed attempts to improve `diagnose_from_dom_diff` on
2026-08-05. Geometric containment for container removals regressed the benchmark
by 6. An ancestry-based reattribution moved the target class by 1.5%, inside the
across-seed spread. A reflow-consistency rule fired on none of the seven cases
it was written for: of those, two moved up, two moved down, three did not move
vertically, four also shifted sideways and four changed width. Each attempt was
trying to resolve a distinction the two snapshots do not determine, because the
underlying events genuinely coincide.

## Decision

Report the strict score. Do not merge the entangled labels.

The tolerant figure is published alongside it, with its grouping stated, because
it carries real information about the nature of the residual error — but it is
not the headline. A taxonomy chosen after seeing which merge raises the number
is a taxonomy fitted to the score, and the strict number stays comparable with
every measurement taken before this analysis existed.

## Consequences

- Classification stays at 94.20%. Roughly four percentage points of the gap to
  100% are label overlap rather than misjudgement, and no amount of work on the
  structural comparison will recover them.
- Effort aimed at raising the strict number should go to the eight errors
  outside those pairs, not the twenty-one inside them.
- If the label set is ever redesigned — a hierarchy, or multi-label output — it
  should be justified by what a reviewer needs to see on a report, and every
  published figure re-measured under it. See
  [ADR 0001](0001-detection-and-classification-are-separate-metrics.md) for why
  detection and classification are already kept apart rather than averaged into
  one headline.
