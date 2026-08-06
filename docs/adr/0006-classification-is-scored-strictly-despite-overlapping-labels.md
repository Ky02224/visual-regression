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
moves trials from wrong to right. Being found that way does not make it wrong —
the labels really were unattainable — but it means it cannot be waved through on
the strength of the reasoning alone. What keeps it falsifiable is that the rule
is stated on the input, so it can be checked without reference to any score.

### What it actually cost, measured

The harness is deterministic given a seed: re-running seed 1000 reproduced all
fifty trials — same sites, same mutation targets, same predictions, 46/50 either
way. Each record also stores both labels (`requested_category` and `expected`),
so the same 500 trials can be scored under both rules with nothing else varying.

```
  old labelling (by which node was deleted) : 470/500 = 94.00%
  new labelling (by what left the page)     : 475/500 = 95.00%
  net effect                                :   +5 trials
```

**All five moved from wrong to right. None moved the other way.** An earlier
draft of this amendment claimed the rule "relabels trials the classifier gets
right just as readily as ones it gets wrong". That is false, and predictably so:
the classifier reads the rendered result, and this rule aligns ground truth with
the rendered result, so it can only ever agree with the classifier more often on
the affected trials. The change is one-directional by construction.

That is not an argument against making it — a label the input does not determine
is not a label worth scoring — but it does mean the +1.00pp is *not* evidence of
anything about the model, and it disposes of any reading in which the harness
was independently confirming the fix. Five trials, all favourable, is what the
argument predicts and therefore not a test of it. The test is the reasoning about
attainability, which stands or falls on its own.

The five affected trials are listed here so the claim is checkable rather than
asserted: two on developer.mozilla.org and books.toscrape.com (seed 1001), two on
old.reddit.com (seeds 1003 and 1004), one on en.wikipedia.org (seed 1007) — each
a `missing-element` request whose removed subtree contained a thumbnail, each
predicted `broken-image`.

The other two pairs — `missing-element`/`layout-issue` and
`text-issue`/`layout-issue` — are untouched. Those are genuine coincidence of
events, not mislabelling, and they continue to be scored strictly.

### The published figure, re-measured

`scripts/live_eval_multiseed.py` was re-run across all ten seeds on 2026-08-06.
**The headline is now 95.00% (475/500), across-seed σ 2.36%, 95% CI
[93.09%, 96.91%]** — `reports/live-eval-summary.json`.

The previous run is kept as `reports/live-eval-summary-prelabelfix.json` rather
than deleted, so the comparison above can be re-derived by anyone who wants to
check it.

Three things about that number, none of which should be skipped when quoting it:

- **It is not an improvement in the system.** +1.00pp of it is the labelling
  correction, which is one-directional by construction (above). Nothing in the
  classifier changed.
- **94.20% and 95.00% are not two measurements of the same thing.** The old file
  says 471/500; scoring today's identical trials under the old rule gives
  470/500. That residual trial is page drift between 2026-08-03 and 2026-08-06,
  not a code change — which is roughly the scale of noise to expect from
  evaluating against live sites at all.
- **The error table at the top of this ADR describes the 2026-08-03 run** and has
  not been re-derived. Its `missing-element -> broken-image` row is the one this
  amendment addresses; the rest should be regenerated from the new per-seed
  files rather than adjusted by hand.

### Determinism, and what the error bar does and does not cover

Re-running a seed reproduces it exactly. That makes the evaluation reproducible
and makes controlled comparisons like the one above possible, but it also means
the 95% CI describes **variation across seed choice only** — it is not a
run-to-run confidence interval, and repeating the whole evaluation will not
resample it. A second run of all ten seeds returns 95.00% again, and that
agreement is not independent evidence of anything.
