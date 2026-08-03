# Architecture

## What the system does

A visual regression is a change to a page that nobody meant to make. This tool
captures a page, compares it against a stored reference image, and classifies
whatever changed so a human only has to look at the changes worth looking at.

Two capabilities, measured separately, because they fail for different reasons:

| Capability | What it answers | Measured at |
|---|---|---|
| **Detection** | Did anything change? | 81/81 injected defects, 0/9 false alarms |
| **Classification** | What kind of change was it? | 94.20% (n=500, 95% CI [92.15%, 96.25%]) |

Detection is pixel arithmetic and is close to exact. Classification is a learned
model and is not. Reporting them as one number would hide which half is weak.

## Request path

```
Browser / CI / Playwright SDK
        │
        ▼
dashboard_server.py ──── app construction, startup, remaining routes
        │
        ├── api/deps.py ............ state accessors + authorisation gates
        ├── api/auth.py ............ login, logout, current user
        ├── api/users.py ........... user management (admin only)
        ├── api/comments.py ........ review comments
        ├── api/scheduler_routes.py  scheduled suites
        ├── api/integrations.py .... webhooks, API key, GitHub OAuth
        ├── api/events.py .......... SSE broadcast registry
        ├── api/files.py ........... static serving + SPA catch-all (mounted LAST)
        └── api/middleware.py ...... request id + timing
        │
        ▼
server_services.py ─── upload and recompare handlers
        │
        ▼
browser.py ──► image_compare.py ──► ai_training.py ──► decision.py
 capture         pixel diff           classification     pass/fail
        │
        ▼
sqlite_store.py / postgres_store.py  (both extend _base_store.BaseStore)
```

## Why the pieces sit where they do

**`api/` is split by domain, not by layer.** Each router owns its routes and the
helpers only it uses. `deps.py` holds what all of them need. The rule that made
the split possible: dependencies read `request.app.state`, never a module-level
`app`, so no router has to import the application back.

**`api/files.py` is mounted last, and that is load-bearing.** Its final route is
`/{path_name:path}`, the SPA fallback. FastAPI matches in registration order, so
mounting it earlier would shadow every API route defined after it and the whole
API would start returning `index.html`. A test asserts no `/api` route is
registered after the catch-all.

**`_base_store.py` holds the logic; the two stores hold the dialect.** Users,
sessions, audit and comments are written once against a `{p}` placeholder. Only
schema creation and the bulk index writers are duplicated, because those differ
in substance (AUTOINCREMENT vs SERIAL, ON CONFLICT syntax) rather than in
punctuation.

**The AI is optional at every point.** When no model is present,
`resolve_ai_model_path` returns `None` and `decision.py` records
`decision_source: "pixel-fallback-no-model"`. The tool still detects changes; it
just stops naming them. This is the path CI takes today.

## Data layout

Everything the tool produces lives under `.visual-regression/`:

```
baselines/<name>/baseline.webp     the reference image
           metadata.json           capture settings, ignore regions
           versions/<ts>/          superseded baselines, kept for rollback
runs/<timestamp>_<case>_<browser>_<device>_<locale>/
           baseline.webp           copy of what it was judged against
           current.webp            what was captured
           diff_overlay.webp       highlighted differences
           result.json             the verdict, scores and decision history
           report.html             standalone report
models/                            trained weights (gitignored — see ADR 0003)
reports/                           suite summaries and AI evaluations
```

A run directory is self-contained on purpose: it carries its own copy of the
baseline, so the report still renders correctly after the baseline is updated.

## Comparison pipeline

1. **Capture** — Playwright, with animations disabled and a fixed viewport,
   locale and timezone. Those three are part of the baseline's identity: the
   same page in two languages is two baselines, not one.
2. **Normalise** — if the page grew or shrank, both images are padded to the
   larger bounds, each with *its own* dominant background colour taken from the
   corners. Padding a dark page with white would make the padding itself the
   largest change in the diff.
3. **Diff** — per-pixel delta above `pixel_threshold`, grouped into regions
   above `min_region_area`, then merged when within `merge_gap` of each other.
4. **Classify** — a ResNet50 siamese head over crops of the changed area, fused
   with rule features (mismatch, SSIM, region geometry). A DOM sidecar captured
   alongside the screenshot supplies structural evidence.
5. **Decide** — `decision.py` combines the pixel verdict, the AI label and the
   threshold. A DOM-confirmed defect bypasses the pixel noise floor: a small
   text change often produces a delta too faint to clear it.

## Authentication

Session cookies (`HttpOnly`, `SameSite=Lax`), PBKDF2-SHA256 at 600k iterations
with a legacy-count fallback, an in-memory per-IP login throttle, and three
roles — admin, developer, viewer.

Automation uses an `X-Access-Key` header instead, checked with
`hmac.compare_digest` against a key stored encrypted in `integrations.json`. It
fails closed: an unconfigured key never matches.

## Running it

```bash
python -m visual_regression.cli serve-dashboard --port 8130   # dashboard
python -m visual_regression.cli run-suite --suite suite.demo.yaml
python -m visual_regression.cli check-ci --max-severity high  # CI gate
```

Observability: `LENS_LOG_FORMAT=json` for structured logs, `/metrics` for
Prometheus counters and latency histograms, `/docs` for the generated OpenAPI
reference.

## Decisions

Recorded in [`docs/adr/`](adr/). The ones most likely to surprise a reader are
the route-ordering constraint (0002) and why baselines must be committed while
models must not (0003).
