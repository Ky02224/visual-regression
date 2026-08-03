# ADR 0003 — Baselines are committed, models and benchmark baselines are not

**Status:** accepted, with one step still outstanding

## Context

`.visual-regression/` is generated output, so the obvious move is to gitignore
all of it. That turned out to be wrong for one specific thing, and right for two
others, for opposite reasons.

**Baselines.** A baseline is the reference a run is judged against. With none
committed, CI captures a baseline from the commit under test and compares it
against itself: `mismatch_pct` is exactly 0.00 and the check *cannot fail*, no
matter what changed. A green visual check meant nothing.

That is not hypothetical. The previous local benchmark — 120 runs across
`bench-*` and `bench100-*` — built each case's baseline from the very
`?defect=` URL it then compared against. All 108 injected-defect cases passed.
The tool looked perfect because it was being asked whether a page matched
itself.

**Models.** The trained weights are large: 318MB checkpoint, 129MB ONNX, 32MB
quantised, ~705MB for the directory. Committing any of them is irreversible
history bloat.

**Benchmark baselines.** These are captured from the clean demo pages, and
`ci.yml` recaptures them with `--overwrite` immediately before every benchmark
run.

## Decision

```gitignore
.visual-regression/*
!.visual-regression/baselines/
.visual-regression/baselines/**/versions/
.visual-regression/baselines/bmk-*/
```

Ignoring the *contents* rather than the directory is what lets the negation
work — git cannot re-include a path whose parent directory is excluded.

- **Baselines: committed.** They are the reference, and without them the check
  is a self-comparison.
- **Archived versions: not committed.** Rollback history, not references.
- **Benchmark (`bmk-*`) baselines: not committed.** CI recaptures them with
  `--overwrite` before every run, so a committed copy would be overwritten and
  never read. Excluding them also stops ~270 dev-machine PNGs being swept in by
  `git add .visual-regression/`.
- **Models: not committed.** Distribution is a separate decision (see below).

## Consequences

- Baselines must be produced on a **Linux runner**, not a dev machine. Chromium
  renders differently on Windows, so a locally captured baseline fails against
  CI for reasons that have nothing to do with the code. The
  `generate-baselines.yml` workflow exists to produce them.
- **Outstanding:** that workflow has to be run, its artifact downloaded,
  unzipped into `.visual-regression/baselines/` and committed. Until then, both
  visual workflows emit a run-summary `::warning::` saying the check is
  self-comparing and cannot detect a regression. The warning is deliberate — a
  green check that proves nothing should say so.
- **Outstanding:** the model still does not reach CI, so `decision.py` records
  `pixel-fallback-no-model` there and the AI half is exercised only locally.
  Getting it there needs a distribution choice — Git LFS, a release asset, or a
  restored cache. A release asset is the cheapest: free, outside git history,
  and easy to explain.
- The `create-suite-baselines` / `run-suite` split in `suites/suite.benchmark.yaml`
  encodes the lesson: `baseline_url` points at the clean page, `url` at the
  defective one. A case where those are equal is a case that cannot fail.
