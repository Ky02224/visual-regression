# 0005 — The SDK uploads DOM, not just pixels

## Status

Accepted, 2026-08-05.

## Context

`sdk/` was modelled on Percy: take a screenshot in an existing Playwright test,
POST it, let the server compare. Percy is a pixel differ, so a screenshot is all
it can use.

This server is not a pixel differ. `diagnose_from_dom_diff` matches individual
elements between the baseline and current snapshots — this `<img>` with this id
and this parent is absent — and that comparison, not pixel arithmetic, is what
produces its change classifications. It needs element data from *both* sides.

An image-only upload therefore disabled it. `assess_result` resolves DOM from a
`<image>.dom.json` sidecar; SDK uploads had no sidecar, so the structural path
had nothing to compare, every structural feature fell to zero, and the
comparison degraded to pixel arithmetic plus a model working from pixel
statistics alone.

That is the wrong way round. A team adopting this tool is far more likely to add
one line to a suite they already have than to hand over their URLs and let the
server drive a browser. Copying Percy's interface meant conceding this tool's
main advantage on the path most likely to be used.

## Decision

The SDK captures a DOM snapshot alongside the screenshot and uploads both. The
server writes it to the `.dom.json` sidecar every downstream consumer already
reads, so structural analysis, structural features and the model all receive it
without further plumbing.

The capture script is served from `/api/sdk/dom-capture-js` rather than
duplicated in TypeScript. A copy would drift: the capture gained per-element
parent indices the same week this was written, and a duplicated script would
have kept producing snapshots without them until someone shipped a matching SDK
release.

Capture failure is not an error. A server too old to serve the script, or a page
that refuses to evaluate it, yields no DOM and the upload proceeds as a
screenshot comparison — the previous behaviour, unchanged.

## Consequences

- An SDK-integrated suite gets the same structural analysis as a locally driven
  capture, instead of falling back to pixel arithmetic.
- Uploads are larger. A snapshot is bounded — capped text per element, elements
  above 2x2px only — and small beside a full-page PNG.
- The SDK now makes two requests on first use, one of them cached for the
  process lifetime.
- `comparison_mode` defaulted to `"ai"` here, which discards the pixel signal
  and lets the model alone decide pass/fail. On a path that also carried no
  structural evidence, that was the weakest possible basis for a verdict. It now
  defaults to `"hybrid"` like every other entry point — see
  [ADR 0001](0001-detection-and-classification-are-separate-metrics.md) for why
  the two signals are kept separable.
