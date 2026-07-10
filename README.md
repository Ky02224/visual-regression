# Visual Regression Workbench

Website-first visual regression platform for QA, frontend engineers and release owners.

## What It Includes

- Website dashboard for runs, reports, approvals and operator actions
- Demo website for end-to-end presentation when no real company site is available
- CLI for automation, CI and low-level control
- Baseline creation, update and version history
- Visual compare and batch suite execution
- Locale / timezone / device aware capture
- AI-assisted change classification with a ResNet50 Siamese + OpenCV/SSIM fusion model
- Public UI dataset ingestion for WebUI / RICO / Screen Annotation manifests
- HTML report, JSON summary and JUnit output

## Setup

```powershell
.\setup.ps1
.\.venv\Scripts\Activate.ps1
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
python -m visual_regression.cli create-suite-baselines --suite suite.cross-matrix.yaml --overwrite
python -m visual_regression.cli run-suite --suite suite.cross-matrix.yaml
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

## Files

- dashboard UI: `dashboard_ui/`
- demo site: `demo_portal/`
- core backend: `visual_regression/`
- runtime artifacts: `.visual-regression/`

## Tests

```powershell
python -m pytest -q
```

## CI, Security and Deployment Notes

- CI: A GitHub Actions workflow has been added at `.github/workflows/ci.yml` to run tests, pip-audit and build the frontend on push/PR. Enable Actions for the repository to use it.
- Dependency updates: Dependabot is configured (`.github/dependabot.yml`) to open weekly updates for Python (pip) and the frontend (npm).
- Secrets/API keys: Do NOT commit API keys to the repository. The dashboard supports an automation access key (X-Access-Key) managed by the Integrations page; store any CI/production keys in your secret manager (GitHub Secrets, Vault, etc.).
- Production deployment: Run the dashboard behind a TLS reverse proxy (nginx, Caddy) and enable HTTPS. Rotate API keys regularly and restrict who can reveal keys via the Integrations UI.


