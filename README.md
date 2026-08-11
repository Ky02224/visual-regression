# Visual Regression Workbench

Website-first visual regression platform for QA, frontend engineers and release owners.

## How This Is Verified

Every claim below is enforced by CI on each push, not measured once by hand.

| Claim | How it is checked |
|---|---|
| Detects 81/81 injected defects, 0/9 false alarms | `Score detection rate` — fails the build on any miss or false alarm |
| The AI inference path actually executes | `Smoke-test the AI inference path` — asserts `decision_source` is not `pixel-fallback-no-model` |
| Classification is 94.80% (n=500), 95% CI [92.85%, 96.75%] | `scripts/live_eval_multiseed.py`, summary committed to `reports/live-eval-summary.json` |
| Both database backends work | `Verify the Postgres parity tests are not skipping` — fails if those tests silently skip |
| 1000 Python + 90 frontend + 8 SDK tests pass | `Run Python tests`, `Run frontend unit tests`, `Run Playwright SDK tests` |

The detection gate runs with `--no-ai` deliberately, so it can never be blocked
by model distribution — see
[ADR 0004](docs/adr/0004-ci-gates-detection-the-ai-is-smoke-tested.md).

That number is not comparable with every earlier one quoted for this project,
and the differences are worth stating rather than smoothing over:

- **Ground-truth labelling was corrected on 2026-08-06.** Trials that deleted a
  wrapper containing a thumbnail had been labelled by which node the mutation
  script picked rather than by what left the page — information neither
  snapshot contains. The correction is worth +5 of 500 and can only move trials
  in the classifier's favour, so it is not evidence of anything about the
  model. The earlier run is kept as
  `reports/live-eval-summary-prelabelfix.json`.
- **The model was retrained on 2026-08-09.** Four inference paths had been
  assembling the rule vector as `[rule, dom, struct]` and zero-padding the
  fifteen pixel-structural columns instead of computing them, so the model was
  trained on evidence it never received in production. Fixing that, and
  retraining with the DOM and image shortcuts partially closed, cost accuracy
  on the with-DOM exam and bought a classifier that no longer leans on
  page-change magnitude alone.
- **The label set was reduced from seven classes to six on 2026-08-11.**
  `layout-issue` is folded into `missing-element`, at inference and in
  ground-truth consolidation alike. Removing an element and the reflow it
  causes are one event seen from two angles, and on the strict seven-way split
  that pair produced the largest single block of residual error. Scored under
  the seven-way rule the same trials give 92.60%
  (`reports/live-eval-summary-7class-20260809.json`); the 94.80% above is the
  six-way rule, which is what the code now does.

The last of those is a taxonomy change made after seeing which merge raised the
number, so it deserves the caveat in full: it is defensible on the grounds that
the two labels describe one event, and it is **not** independent evidence that
the classifier improved.

Baselines are captured inside this project's Docker image
(`scripts/generate_linux_baselines.sh`) rather than on a developer machine.
Chromium renders text differently across platforms and font sets, so a baseline
from anywhere else fails for reasons unrelated to the page — and a check that
captures its own reference from the commit under test cannot fail at all.

## What It Includes

- Website dashboard for runs, reports, approvals and operator actions
- Demo website for end-to-end presentation when no real company site is available
- CLI for automation, CI and low-level control
- Baseline creation, update and version history
- Visual compare and batch suite execution
- Locale / timezone / device aware capture
- Change classification from structural DOM comparison fused with a ResNet50
  Siamese + OpenCV/SSIM model
- Playwright SDK that uploads DOM alongside screenshots, so an existing suite
  gets structural analysis rather than pixel-only comparison
- Public UI dataset ingestion for WebUI / RICO / Screen Annotation manifests
- HTML report, JSON summary and JUnit output
- Role-based access control (admin / developer / viewer) with session auth
- SQLite by default, with an optional PostgreSQL backend via `DATABASE_URL`
- GitHub OAuth integration for repo commit-status checks
- Docker deployment via `docker-compose up`

## Setup

```powershell
.\setup.ps1
.\.venv\Scripts\Activate.ps1
```

Or with Docker:

```bash
cp .env.example .env   # set LENS_ADMIN_PASSWORD / LENS_DEVELOPER_PASSWORD
docker-compose up --build
```

## Main Way To Use It

Start the website-first dashboard:

```powershell
python -m visual_regression.cli serve-dashboard --port 8130
```

Open:

```text
http://127.0.0.1:8130/
```

## Dashboard Workflow

From the dashboard you can:
- create a baseline from a URL
- update a single baseline and keep previous versions archived
- run a single compare directly from a form
- run a whole suite from a YAML file
- filter runs by status, decision, browser, device and locale
- inspect run detail with mismatch, severity, AI assessment and decision history
- inspect baseline thumbnails, metadata and archived versions
- inspect recent suite summaries
- approve or reject a run and update the report immediately

## Demo URLs

The dashboard also serves the demo website under `/demo/`.

Examples:
- `http://127.0.0.1:8130/demo/index.html?lang=en-US`
- `http://127.0.0.1:8130/demo/login.html?lang=ms-MY`
- `http://127.0.0.1:8130/demo/dashboard.html?lang=zh-CN`
- `http://127.0.0.1:8130/demo/index.html?lang=en-US&defect=missing-cta`

## CLI Still Available

CLI is still useful for automation and CI:

```powershell
python -m visual_regression.cli create-suite-baselines --suite suite.demo.yaml --overwrite
python -m visual_regression.cli train-ai --epochs 20 --samples-per-image 12
python -m visual_regression.cli run-suite --suite suite.demo.yaml
python -m visual_regression.cli list-runs
```

For cross-browser testing, install all Playwright browsers first:

```powershell
.\setup.ps1 -InstallAllBrowsers
python -m visual_regression.cli create-suite-baselines --suite suites\suite.cross-matrix.yaml --overwrite
python -m visual_regression.cli run-suite --suite suites\suite.cross-matrix.yaml
```

## AI Workflow

Current AI can be trained only from project data, or from project data plus public UI screenshots.

1. Build a manifest from locally extracted public datasets:

```powershell
python -m visual_regression.cli prepare-public-datasets `
  --webui-dir C:\datasets\webui `
  --rico-dir C:\datasets\rico `
  --screen-annotation-dir C:\datasets\screen_annotation
```

2. Train the model with the generated manifest:

```powershell
python -m visual_regression.cli train-ai `
  --dataset-manifest .visual-regression\datasets\public-ui-manifest.json `
  --epochs 12 `
  --samples-per-image 8 `
  --batch-size 4 `
  --max-public-images 300
```

3. Evaluate the trained model against stored run data:

```powershell
python -m visual_regression.cli evaluate-ai
```

The training metadata is written to `.visual-regression\models\visual_ai.json`.
Evaluation summaries are written to `.visual-regression\reports\ai-eval-*.json` and `.visual-regression\reports\ai-run-eval-*.json`.

### Optional: plain-language narration

Each classified change already carries an explanation derived from the two DOM
snapshots — a specific claim that can be checked against the page, e.g. *"the
`<img>` at (399,417) still occupies its 127x155 box but decoded to nothing
(naturalWidth 0)"*. Setting `VRT_ENABLE_OLLAMA=true` **appends** a readable
narration of the same crop, produced by a local Ollama vision model:

```powershell
ollama serve
ollama pull llava
$env:VRT_ENABLE_OLLAMA = "true"
```

It is off by default and appended rather than substituted on purpose: the
narration is generated text and the evidence is not, so a reviewer acting on a
verdict should see the checkable sentence first. If Ollama is unreachable the
narration is skipped and the evidence is left exactly as it was.

## Playwright SDK

`sdk/` is a TypeScript package that lets an existing Playwright suite send
snapshots to this server, as a drop-in alternative to Percy:

```typescript
import { visualSnapshot } from '../vr-sdk/dist/index';

test('homepage looks correct', async ({ page }) => {
  await page.goto('https://example.com');
  await visualSnapshot(page, 'homepage');
});
```

That one line uploads the DOM as well as the screenshot, which is what separates
this from a pixel differ. Structural comparison needs element data from both
sides, so an image-only upload leaves it nothing to work with; the SDK already
holds a Playwright `Page`, so the snapshot is one `evaluate()` away. Suites that
integrate this way get the same structural analysis as a locally driven capture
rather than falling back to pixel arithmetic.

The capture script is fetched from `/api/sdk/dom-capture-js` rather than
duplicated in TypeScript, so the two cannot drift — a field added to the capture
reaches clients without an SDK release. A page that refuses to run it still
uploads a working screenshot comparison.

Build it with `cd sdk && npm install && npm run build`. Authentication uses the
automation access key from the Integrations page (`VR_API_KEY`). See
[sdk/README.md](sdk/README.md) for the full API.

## Measured Results

Detection and classification are reported separately because they fail for
different reasons — see [ADR 0001](docs/adr/0001-detection-and-classification-are-separate-metrics.md).

| Capability | Result | Evaluation set |
|---|---|---|
| **Defect detection** | **81/81 detected, 0/9 false alarms** | Injected defects on the demo portal, ground truth from the injected mode |
| **Change classification** | **94.80%**, 95% CI [92.85%, 96.75%], across-seed σ 3.01% | Real third-party pages with injected DOM mutations, n=500 over 10 seeds |
| Classification (synthetic) | 87.6% — a *validation* score, calibration fitted on the same set | 12,000 synthetic mutations |

Reproduce the second row with:

```bash
python scripts/live_eval_multiseed.py --seeds 10 --trials 50
```

The 26 residual errors on that run are not spread evenly across the label set:

```
  8  missing-element   -> font-change
  7  missing-element   -> color-regression
  5  text-issue        -> missing-element
  3  broken-image      -> insignificant-change
  2  missing-element   -> text-issue
  1  color-regression  -> insignificant-change
```

Seventeen of them start from `missing-element`, whose recall (87.7%) is the
lowest of the six. That is where the remaining work is. The four scored as
`insignificant-change` are a different failure: the change was real but small
enough that the noise floor discarded it before the label mattered.

## Documentation

- [Architecture](docs/architecture.md) — how the pieces fit and why
- [Decision records](docs/adr/) — the choices that would otherwise look arbitrary
- `/docs` on a running server — generated OpenAPI reference

## Observability

```bash
LENS_LOG_FORMAT=json python -m visual_regression.cli serve-dashboard
```

One JSON object per line, with `extra=` fields as top-level keys. Every response
carries `X-Request-ID` and `X-Response-Time-Ms`; the id appears on every log line
emitted while handling that request, so one can be pasted from a browser's
network tab straight into a log search. `/metrics` exposes Prometheus counters
and latency histograms.

## Files

- dashboard UI: `dashboard_frontend/`
- demo site: `demo_portal/`
- core backend: `visual_regression/`
- HTTP layer: `visual_regression/api/`
- Playwright SDK: `sdk/`
- benchmark tooling: `scripts/generate_benchmark_suite.py`, `scripts/benchmark_report.py`
- runtime artifacts: `.visual-regression/`

## Detection Benchmark

Passing tests show the tool does not raise false alarms. They do not show it
catches anything. The benchmark is the positive test: it captures baselines from
the **clean** demo pages, then compares each page loaded with `?defect=<mode>`
against them. A case that passes is a missed defect.

```powershell
python scripts\generate_benchmark_suite.py
python -m visual_regression.cli create-suite-baselines --suite suites\suite.benchmark.yaml --overwrite
python -m visual_regression.cli run-suite --suite suites\suite.benchmark.yaml --no-junit
python scripts\benchmark_report.py --json-out reports\benchmark-summary.json
```

The report gives, per injected defect type:

- **detection rate** — share of defective cases flagged (recall on known-bad input)
- **false alarms** — control cases (clean vs clean) flagged anyway
- **AI label accuracy** — of the defects caught, how often the AI named the right
  change type, scored only on caught cases

Ground truth comes from the injected mode encoded in each case name, not from the
model's own output, so this is an external benchmark. `benchmark_report.py` exits
non-zero on any miss, any control-group false alarm, or a partial run, which is
what lets CI gate on it.

## Tests

```powershell
python -m pytest -q
python -m ruff check .
```

## CI, Security and Deployment Notes

- CI: A GitHub Actions workflow has been added at `.github/workflows/ci.yml` to run tests, pip-audit and build the frontend on push/PR. Enable Actions for the repository to use it.
- Dependency updates: Dependabot is configured (`.github/dependabot.yml`) to open weekly updates for Python (pip) and the frontend (npm).
- Secrets/API keys: Do NOT commit API keys to the repository. The dashboard supports an automation access key (X-Access-Key) managed by the Integrations page; store any CI/production keys in your secret manager (GitHub Secrets, Vault, etc.).
- Production deployment: Run the dashboard behind a TLS reverse proxy (nginx, Caddy) and enable HTTPS. Rotate API keys regularly and restrict who can reveal keys via the Integrations UI.


