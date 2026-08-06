# 0006 — Classification is scored strictly, despite overlapping labels

## Status

Accepted, 2026-08-05. Amended 2026-08-06 — see
[Amendment](#amendment-2026-08-06--one-of-the-three-pairs-was-a-labelling-defect).

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

## Amendment, 2026-08-06 — one of the three pairs was a labelling defect

The decision above stands. One of the three entangled pairs, however, turned out
not to be entanglement at all, but a bug in how the harness assigned ground
truth — and that has to be separated from the merge this ADR refuses, because
the two look similar and are not.

`scripts/live_dom_mutation_eval.py` labels a trial by **which node its mutation
script deleted**. Its `missing-element` mutation picks from `p/span/a/div/li`.
On real pages those routinely wrap a thumbnail — `<a><img></a>` is the ordinary
card and nav pattern — so when the picker happened to choose such a wrapper, the
harness recorded `missing-element` while what actually left the page was an
image. Both snapshots show an `<img>` present before and absent after. Nothing
in the input distinguishes that from deleting the `<img>` directly.

So the expected answer was not merely hard to reach; it was **not a function of
the input**. The harness was scoring the classifier on which node the mutation
script happened to select, which the classifier is never shown. The fix labels
by what left the page: if the removed subtree took a media element with it, the
trial is a `broken-image` trial.

### Why this is not the merge this ADR rejects

The distinction that matters is *when the rule can be evaluated*:

- A **scoring merge** changes what counts as correct for a given prediction. It
  can only be applied after a prediction exists, and the pairs to merge are
  chosen by looking at which ones are getting missed. That is fitting the
  taxonomy to the score, and it stays refused.
- This change alters the **stimulus→label** function in the trial generator. It
  is decidable from the mutation alone, before any model runs, and it is stated
  as a property of the page ("did a media element leave?") rather than as a
  relation between two labels.

The honest caveat: this defect was found by grouping the residual errors, and it
happens to move six of them from wrong to right. Being found that way does not
make it wrong — the labels really were unattainable — but it does mean it cannot
be waved through on the strength of the reasoning alone. What keeps it
falsifiable is that the rule is stated on the input, so it can be checked
without reference to any score, and it relabels trials the classifier gets right
just as readily as ones it gets wrong.

The other two pairs — `missing-element`/`layout-issue` and
`text-issue`/`layout-issue` — are untouched. Those are genuine coincidence of
events, not mislabelling, and they continue to be scored strictly.

### Consequence: the published figure is stale

**94.20% was measured under the old labelling and is not comparable to anything
measured after this change.** Until `scripts/live_eval_multiseed.py` is re-run
across all ten seeds:

- `reports/live-eval-summary.json` and the 94.20% in the README's verification
  table describe the previous ground truth.
- The error table at the top of this ADR describes that same previous run. The
  six `missing-element -> broken-image` rows are the ones this amendment
  reclassifies; the remaining counts should be re-derived, not adjusted by hand.

The re-run is the outstanding work. No figure from it should be published
alongside the old one without saying which labelling each was measured under.
