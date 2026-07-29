"""
tests/test_e2e_dom_diff_pipeline.py
────────────────────────────────────
Genuine end-to-end coverage of the real create-baseline → compare pipeline:
real HTTP request -> real subprocess CLI invocation -> real Playwright
browser capture -> real DOM snapshot -> real comparison -> real DOM-diff
classification.

This exists because the entire DOM-diff feature was silently dead for every
baseline created through the real `create-baseline` CLI/dashboard entry
point for an unknown length of time: `capture_website()` correctly wrote a
`.dom.json` sidecar next to the captured image, but `save_from_image()` only
ever copied the image into the final baseline directory, never the sidecar.
Every existing test that caught the DOM-diff logic working called
`diagnose_from_dom_diff()` (or `assess_result()`) directly with in-memory
element lists — none of them went through the real capture-and-save path,
so none of them could have caught this. A unit test of the matching logic
proves the logic is correct; it says nothing about whether real callers
ever actually feed it real data.
"""
from __future__ import annotations

import json
import shutil
import socket
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from tests.test_functional_e2e import _login, _api
from visual_regression.config import WorkspacePaths
from visual_regression.dashboard_server import DashboardHandler
from visual_regression.sqlite_store import SqliteStore

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def srv(tmp_path):
    """Like test_functional_e2e.srv, but with project_root pointed at the
    real repo checkout instead of the isolated tmp_path.

    Subprocess-mode CLI actions (see _run_cli_action_helper) resolve
    `visual_regression` on PYTHONPATH via `project_root`, not via
    `paths.root`. The two are separate concepts — project_root is "where
    the package source lives", paths.root is "where this test's workspace
    artifacts get written" — but the shared srv fixture collapses them onto
    the same throwaway tmp_path, which happens to work for every existing
    test only because none of them exercise the subprocess path (they all
    use /api/sdk/snapshot, a direct in-process image upload with no CLI
    invocation). Any real create-baseline/compare call needs project_root
    to actually resolve the package, while still keeping paths.root
    isolated so no test artifacts land in the real .visual-regression/.
    """
    project_root = _REPO_ROOT
    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    paths.ensure()

    store = SqliteStore(paths.db_path)
    store.ensure_bootstrap_users()

    port = _free_port()

    class _QuietServer(ThreadingHTTPServer):
        def log_message(self, *_):
            pass

    handler = partial(DashboardHandler, project_root=project_root, paths=paths, port=port)
    server = _QuietServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    yield port, paths, store

    server.shutdown()
    server.server_close()
    t.join(timeout=2)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


_PAGE_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>e2e fixture</title></head>
<body>
  <h1>Fixture page</h1>
  <section id="cta" style="width:300px;height:80px;background:#eee;">
    <p>Call to action content</p>
  </section>
  <script>
    var params = new URLSearchParams(location.search);
    if (params.get('defect') === 'missing') {
      document.getElementById('cta').style.display = 'none';
    }
  </script>
</body></html>
"""


@pytest.fixture()
def fixture_page(tmp_path):
    page_path = tmp_path / "e2e_fixture.html"
    page_path.write_text(_PAGE_HTML, encoding="utf-8")
    return page_path


def test_real_create_baseline_writes_dom_sidecar(srv, fixture_page):
    """Regression test for the sidecar-orphaning bug: a baseline created
    through the real /api/actions/create-baseline endpoint (real subprocess,
    real Playwright capture) must end up with BOTH the image and the
    .dom.json sidecar in the final baseline directory, not just the image.
    """
    port, paths, _store = srv
    cookie = _login(port)

    status, data = _api(
        port, "/api/actions/create-baseline",
        method="POST",
        body={"name": "e2e-sidecar-check", "url": fixture_page.as_uri()},
        cookie=cookie,
    )
    assert status == 200, f"create-baseline failed: {status} {data}"
    assert data.get("ok") is True, data

    baseline_dir = paths.baselines_dir / "e2e-sidecar-check"
    assert baseline_dir.is_dir(), "Baseline directory was not created"
    images = list(baseline_dir.glob("baseline.*"))
    assert any(p.suffix in (".png", ".webp") for p in images), (
        f"No baseline image found in {baseline_dir}: {list(baseline_dir.iterdir())}"
    )
    sidecar = baseline_dir / "baseline.dom.json"
    assert sidecar.is_file(), (
        f"baseline.dom.json sidecar is missing from {baseline_dir} "
        f"(contents: {list(baseline_dir.iterdir())}) — DOM-diff has no data "
        f"to compare against for any comparison run against this baseline."
    )
    elements = json.loads(sidecar.read_text(encoding="utf-8"))
    els = elements if isinstance(elements, list) else elements.get("elements", elements)
    assert any(e.get("tag") == "section" for e in els), (
        "Sidecar exists but doesn't contain the expected <section> element "
        "captured from the fixture page"
    )


def test_real_compare_uses_dom_diff_for_missing_element(srv, fixture_page):
    """End-to-end: baseline captured via the real endpoint, then compared
    against a mutated real page load through the real endpoint, must
    produce a DOM-diff-backed "missing" explanation — not just a pixel
    mismatch percentage with no structural evidence.

    Subprocess-mode `compare` (the path this test's server config always
    uses) only returns {ok, returncode, stdout, stderr} over HTTP — the
    structured per-field result (mismatch_pct, ai_explanation, ...) is
    never echoed back in the response, only printed as text and written to
    result.json in the run directory. Reading that file directly is what
    the real dashboard frontend effectively does too (via a separate
    dashboard-data fetch), so this isn't testing a shortcut — it's testing
    the same artifact the UI actually renders from.

    Also: the AI/DOM-diff path only activates when a trained model exists
    in this workspace's models dir (see resolve_ai_model_path) — an
    isolated tmp_path workspace has none by default, so without copying
    the real trained model in, `compare` silently falls back to a
    pixel-only decision that never calls assess_result() or DOM-diff at
    all, and this test would pass for the wrong reason.
    """
    port, paths, _store = srv
    cookie = _login(port)

    real_model = _REPO_ROOT / ".visual-regression" / "models" / "visual_ai.pt"
    if not real_model.is_file():
        pytest.skip("No trained model checkpoint present in this checkout to test against")
    paths.models_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(real_model, paths.models_dir / "visual_ai.pt")

    baseline_url = fixture_page.as_uri()
    status, data = _api(
        port, "/api/actions/create-baseline",
        method="POST",
        body={"name": "e2e-dom-diff-check", "url": baseline_url},
        cookie=cookie,
    )
    assert status == 200 and data.get("ok"), f"create-baseline failed: {data}"

    defect_url = baseline_url + "?defect=missing"
    status, data = _api(
        port, "/api/actions/compare",
        method="POST",
        body={"name": "e2e-dom-diff-check", "url": defect_url},
        cookie=cookie,
    )
    # A comparison that legitimately detects a real regression is reported
    # as HTTP 500 with ok=False here (the CLI's compare command exits
    # non-zero on FAIL for CI-integration purposes, and this endpoint maps
    # any non-zero CLI exit code to a 500 status) — that conflates
    # "the command itself errored" with "the comparison correctly failed",
    # which is a pre-existing API quirk, not something this test is
    # checking. Assert the CLI process at least ran and produced output,
    # then verify the actual result from the written report.
    assert status in (200, 500) and data.get("stdout"), f"compare didn't run: {status} {data}"
    assert "[FAIL]" in data["stdout"], f"Expected the CLI to report FAIL: {data['stdout']}"

    run_dirs = sorted(
        (d for d in paths.runs_dir.iterdir() if d.is_dir() and "e2e-dom-diff-check" in d.name),
        key=lambda d: d.stat().st_mtime, reverse=True,
    )
    assert run_dirs, f"No run directory found under {paths.runs_dir}: {list(paths.runs_dir.iterdir())}"
    result_json = json.loads((run_dirs[0] / "result.json").read_text(encoding="utf-8"))

    assert result_json.get("status") == "FAIL", (
        f"Expected a real, detected regression, got status={result_json.get('status')!r}: {result_json}"
    )
    explanation = result_json.get("ai_explanation") or ""
    assert "DOM diff" in explanation, (
        f"Expected a DOM-diff-backed explanation for a real element removal, "
        f"got: {explanation!r} (full result.json: {result_json})"
    )
    assert "section" in explanation.lower(), explanation

    # Close the loop through the actual mechanism real CI pipelines call to
    # decide whether to block a deploy — not just the comparison's own
    # status field. A real, DOM-diff-confirmed defect with a small pixel
    # footprint can legitimately score as "medium" severity (below the
    # default "high" --max-severity threshold), so this specifically
    # verifies check-ci's status-aware gating (see cmd_check_ci) against
    # data this test's own real compare run actually produced, not a
    # hand-crafted result.json.
    import argparse
    from visual_regression.cli import cmd_check_ci
    rc = cmd_check_ci(argparse.Namespace(max_severity="high", viewports="desktop"), paths)
    assert rc == 1, (
        f"check-ci should have blocked the build for a confirmed FAIL, "
        f"got exit code {rc} (severity was {result_json.get('severity')})"
    )
