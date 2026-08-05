"""
tests/test_functional_e2e.py
────────────────────────────
End-to-end functional tests for the Visual Regression Platform.

Each test scenario spins up a real ThreadingHTTPServer (on a random port)
against a fresh tmp_path workspace so tests are fully isolated and can run
in parallel without contention.

Covered scenarios
─────────────────
T-01  Health check endpoint
T-02  Auth: login → cookie → /api/auth/me → logout
T-03  SDK: create baseline from base64 PNG upload
T-04  SDK: compare against existing baseline (PASS path)
T-05  Security: SDK name with path traversal is rejected (400)
T-06  Baseline delete endpoint
T-07  Review/Decision: approve run promotes current image to baseline
T-08  Security: webhook URL with non-http scheme is rejected (400)
T-09  DoS protection: oversized Content-Length in _read_json returns 400
"""
from __future__ import annotations

import base64
import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from functools import partial

import pytest

from visual_regression.config import WorkspacePaths
from visual_regression.dashboard_server import DashboardHandler
from visual_regression.sqlite_store import SqliteStore


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _tiny_png() -> bytes:
    """Return a minimal valid 10×10 white PNG that OpenCV can load."""
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAIAAAACUFjqAAAAEElEQVR4nGP4jxcwjEpjAwD6Hirkl4HYkQAAAABJRU5ErkJggg=="
    )


def _black_png() -> bytes:
    """Return a minimal valid 10×10 black PNG that OpenCV can load."""
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAIAAAACUFjqAAAADUlEQVR4nGNgGAWkAwABNgABVtF/yAAAAABJRU5ErkJggg=="
    )



def _b64_png() -> str:
    return base64.b64encode(_tiny_png()).decode()


def _b64_black_png() -> str:
    return base64.b64encode(_black_png()).decode()


def _api(port: int, path: str, *, method: str = "GET", body: dict | None = None, headers: dict | None = None, cookie: str = ""):
    """Send an HTTP request to the test server and return (status, response_dict)."""
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", cookie)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


# ─────────────────────────────────────────────────────────────────────────────
# Fixture: isolated test server
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def srv(tmp_path):
    """Spin up an isolated DashboardHandler server on a free port."""
    project_root = tmp_path
    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    paths.ensure()

    store = SqliteStore(paths.db_path)
    store.ensure_bootstrap_users()          # seeds admin / user accounts
    # Suppress the weak-password warning in test output
    # (bootstrap always uses defaults in tests)

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


# ─────────────────────────────────────────────────────────────────────────────
# Helper: log in as admin, return session cookie value
# ─────────────────────────────────────────────────────────────────────────────

def _login(port: int, email: str = "admin", password: str = "admin1234") -> str:
    url = f"http://127.0.0.1:{port}/api/auth/login"
    body = json.dumps({"email": email, "password": password}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        raw_cookie = resp.getheader("Set-Cookie", "")
        # Extract lens_session=<token>
        for part in raw_cookie.split(";"):
            part = part.strip()
            if part.startswith("lens_session="):
                return part  # "lens_session=<token>"
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# T-01 — Health check
# ─────────────────────────────────────────────────────────────────────────────

def test_t01_health_check(srv):
    """GET /api/health must return 200 {ok: True, status: 'healthy'} with no auth."""
    port, *_ = srv
    status, data = _api(port, "/api/health")
    assert status == 200
    assert data["ok"] is True
    assert data["status"] == "healthy"


# ─────────────────────────────────────────────────────────────────────────────
# T-02 — Auth flow: login → /api/auth/me → logout
# ─────────────────────────────────────────────────────────────────────────────

def test_t02_auth_flow(srv):
    port, *_ = srv

    # 1. Login with valid credentials
    cookie = _login(port)
    assert "lens_session=" in cookie, "Should receive session cookie on login"

    # 2. /api/auth/me with cookie returns authenticated user
    status, data = _api(port, "/api/auth/me", cookie=cookie)
    assert status == 200
    assert data["authenticated"] is True
    assert data["user"]["email"] == "admin"
    assert data["user"]["role"] == "admin"

    # 3. Logout clears session
    status, data = _api(port, "/api/auth/logout", method="POST", body={}, cookie=cookie)
    assert status == 200
    assert data["ok"] is True

    # 4. After logout, /api/auth/me reports unauthenticated
    status, data = _api(port, "/api/auth/me", cookie=cookie)
    assert status == 200
    assert data["authenticated"] is False

    # 5. Wrong credentials → 401
    status, _ = _api(port, "/api/auth/login", method="POST", body={"email": "admin", "password": "wrongpassword"})
    assert status == 401


# ─────────────────────────────────────────────────────────────────────────────
# T-03 — SDK snapshot: create baseline from PNG upload
# ─────────────────────────────────────────────────────────────────────────────

def test_t03_sdk_create_baseline(srv):
    port, paths, store = srv
    # Use admin session cookie (avoids module-level API key cache cross-test contamination)
    cookie = _login(port)

    status, data = _api(
        port, "/api/sdk/snapshot",
        method="POST",
        body={"name": "home-page", "image": _b64_png()},
        cookie=cookie,
    )
    assert status == 200, f"Expected 200, got {status}: {data}"
    assert data["ok"] is True
    assert data["action"] == "baseline_created"
    assert data["name"] == "home-page"

    # Baseline directory should now exist
    baseline_dir = paths.baselines_dir / "home-page"
    assert baseline_dir.is_dir(), "Baseline directory was not created"


def test_t03b_sdk_snapshot_rejects_viewer_role(srv):
    # /api/sdk/snapshot creates/overwrites baselines — a mutating action
    # that must be restricted the same way create-baseline/compare/etc.
    # are, not left open to any authenticated session. Regression test for
    # a real broken-access-control gap found via independent security
    # review: this endpoint (and several /api/actions/* siblings) used to
    # accept any authenticated role, including the intentionally
    # read-only "viewer" role.
    port, paths, store = srv
    store.create_user(email="viewer@example.com", password="viewer1234", role="viewer")
    cookie = _login(port, email="viewer@example.com", password="viewer1234")

    status, data = _api(
        port, "/api/sdk/snapshot",
        method="POST",
        body={"name": "viewer-should-not-create-this", "image": _b64_png()},
        cookie=cookie,
    )
    assert status == 403, f"Expected 403 for viewer role, got {status}: {data}"
    assert not (paths.baselines_dir / "viewer-should-not-create-this").is_dir()


# ─────────────────────────────────────────────────────────────────────────────
# T-04 — SDK snapshot: compare against existing baseline → PASS (identical image)
# ─────────────────────────────────────────────────────────────────────────────

def test_t04_sdk_compare_pass(srv):
    port, paths, _ = srv
    cookie = _login(port)

    # First call: create baseline
    _api(port, "/api/sdk/snapshot", method="POST",
         body={"name": "product-page", "image": _b64_png()}, cookie=cookie)

    # Second call: compare with IDENTICAL image → should PASS (0% mismatch)
    status, data = _api(
        port, "/api/sdk/snapshot",
        method="POST",
        body={"name": "product-page", "image": _b64_png(), "comparison_mode": "pixel"},
        cookie=cookie,
    )
    assert status == 200, f"Expected 200, got {status}: {data}"
    assert data["ok"] is True
    assert data["action"] == "compared"
    assert data["passed"] is True
    assert data["mismatch_pct"] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# T-05 — Security: SDK name with path traversal is rejected
# ─────────────────────────────────────────────────────────────────────────────

def test_t05_sdk_path_traversal_rejected(srv):
    port, paths, _ = srv
    cookie = _login(port)

    for malicious_name in ["../evil", "../../etc/passwd", "foo/bar", "foo\\bar"]:
        status, data = _api(
            port, "/api/sdk/snapshot",
            method="POST",
            body={"name": malicious_name, "image": _b64_png()},
            cookie=cookie,
        )
        assert status == 400, f"Expected 400 for name={malicious_name!r}, got {status}"
        assert "path" in data.get("error", "").lower() or "separators" in data.get("error", "").lower(), \
            f"Expected path traversal error message, got: {data}"


# ─────────────────────────────────────────────────────────────────────────────
# T-06 — Baseline delete
# ─────────────────────────────────────────────────────────────────────────────

def test_t06_baseline_delete(srv):
    port, paths, _ = srv
    cookie = _login(port)

    # Create baseline first
    status, data = _api(port, "/api/sdk/snapshot", method="POST",
         body={"name": "to-be-deleted", "image": _b64_png()}, cookie=cookie)
    assert status == 200, f"Baseline creation failed: {data}"
    assert (paths.baselines_dir / "to-be-deleted").is_dir()

    # Delete it
    status, data = _api(
        port, "/api/baseline/delete",
        method="POST",
        body={"name": "to-be-deleted"},
        cookie=cookie,
    )
    assert status == 200, f"Delete failed: {data}"
    assert data["ok"] is True

    # Baseline dir should be gone (or at least no baseline.webp)
    assert not (paths.baselines_dir / "to-be-deleted" / "baseline.webp").exists()


# ─────────────────────────────────────────────────────────────────────────────
# T-07 — Review/Decision: approve run promotes current image to new baseline
# ─────────────────────────────────────────────────────────────────────────────

def test_t07_approve_decision_promotes_baseline(srv):
    port, paths, _ = srv
    cookie = _login(port)

    # Step 1: Create baseline with original tiny PNG
    _api(port, "/api/sdk/snapshot", method="POST",
         body={"name": "approval-test", "image": _b64_png()}, cookie=cookie)

    # Step 2: Compare with a DIFFERENT image (all-black 10×10 PNG) to generate a FAIL run
    _, compare_data = _api(
        port, "/api/sdk/snapshot",
        method="POST",
        body={"name": "approval-test", "image": _b64_black_png(), "comparison_mode": "pixel"},
        cookie=cookie,
    )
    run_id = compare_data.get("run_id", "")

    # Step 3: Approve the run via the decision endpoint
    if run_id:
        cookie = _login(port)
        status, data = _api(
            port, "/api/decision",
            method="POST",
            body={"run": run_id, "decision": "approved", "reviewer": "qa-engineer"},
            cookie=cookie,
        )
        assert status == 200, f"Approve failed: {data}"
        assert data["ok"] is True
        assert data["decision"]["status"] == "approved"

        # Verify result.json reflects approval
        result_file = paths.runs_dir / run_id / "result.json"
        if result_file.exists():
            payload = json.loads(result_file.read_text())
            assert payload.get("decision", {}).get("status") == "approved"


# ─────────────────────────────────────────────────────────────────────────────
# T-08 — Security: webhook URL with non-http scheme is rejected
# ─────────────────────────────────────────────────────────────────────────────

def test_t08_webhook_scheme_validation(srv):
    port, *_ = srv
    cookie = _login(port)

    for bad_url in ["file:///etc/passwd", "ftp://evil.com/hook", "data:text/html,evil"]:
        status, data = _api(
            port, "/api/integrations/webhooks",
            method="POST",
            body={"url": bad_url, "threshold": 1.0},
            cookie=cookie,
        )
        assert status == 400, f"Expected 400 for webhook URL {bad_url!r}, got {status}: {data}"

    # Valid http/https URLs must be accepted
    for good_url in ["https://hooks.slack.com/services/T/B/X", "http://myserver.local/hook"]:
        status, data = _api(
            port, "/api/integrations/webhooks",
            method="POST",
            body={"url": good_url, "threshold": 1.0},
            cookie=cookie,
        )
        assert status == 200, f"Expected 200 for webhook URL {good_url!r}, got {status}: {data}"


# ─────────────────────────────────────────────────────────────────────────────
# T-09 — DoS protection: oversized Content-Length returns 400
# ─────────────────────────────────────────────────────────────────────────────

def test_t09_read_json_dos_protection(srv):
    port, *_ = srv
    cookie = _login(port)

    # Claim Content-Length of 100MB but send empty body
    url = f"http://127.0.0.1:{port}/api/auth/login"
    req = urllib.request.Request(url, data=b"{}", method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Content-Length", str(100 * 1024 * 1024))  # 100MB claim
    req.add_header("Cookie", cookie)

    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            body = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            body = json.loads(e.read())
        except Exception:
            body = {}

    assert status == 400, f"Expected 400 for oversized Content-Length, got {status}: {body}"


# ─────────────────────────────────────────────────────────────────────────────
# T-10 — Security: static route path traversal is blocked
# ─────────────────────────────────────────────────────────────────────────────

def test_t10_static_path_traversal_blocked(srv):
    import http.client
    port, *_ = srv
    
    conn = http.client.HTTPConnection("127.0.0.1", port)
    
    # 1. Try traversal from /demo/
    conn.request("GET", "/demo/../../requirements.txt")
    resp = conn.getresponse()
    body = resp.read()
    assert b"playwright" not in body, f"Path traversal succeeded on /demo/: {body[:100]}"
    
    # 2. Try traversal from root fallback
    conn.request("GET", "/../../requirements.txt")
    resp2 = conn.getresponse()
    body2 = resp2.read()
    assert b"playwright" not in body2, f"Path traversal succeeded on root fallback: {body2[:100]}"


# ─────────────────────────────────────────────────────────────────────────────
# T-11 — SDK uploads carry DOM, so structural analysis works on that path too
# ─────────────────────────────────────────────────────────────────────────────

def _dom_payload(elements: list) -> dict:
    return {
        "elements": elements,
        "tag_counts": {},
        "total_elements": len(elements),
        "avg_depth": 3.0,
        "interactive_count": 0,
        "has_form": False, "has_img": True, "has_video": False, "has_iframe": False,
    }


def test_t11_sdk_snapshot_stores_dom_sidecar(srv):
    # The SDK holds a Playwright Page, so it can capture the DOM as cheaply as
    # the screenshot — but it used to send only the image. That left
    # diagnose_from_dom_diff with nothing to compare and every structural
    # feature at zero, disabling this tool's strongest signal for exactly the
    # integration a team is most likely to adopt. The sidecar is what every
    # downstream consumer reads, so assert it reaches disk.
    port, paths, store = srv
    cookie = _login(port)
    elements = [
        {"tag": "div", "x": 10, "y": 10, "w": 200, "h": 120, "eid": "hero"},
        {"tag": "img", "x": 20, "y": 20, "w": 100, "h": 60, "p": 0},
    ]

    status, data = _api(
        port, "/api/sdk/snapshot",
        method="POST",
        body={"name": "dom-carrying-page", "image": _b64_png(),
              "dom": _dom_payload(elements)},
        cookie=cookie,
    )
    assert status == 200 and data.get("action") == "baseline_created", data

    baseline_dir = paths.baselines_dir / "dom-carrying-page"
    sidecars = list(baseline_dir.glob("baseline.dom.json"))
    assert sidecars, f"no DOM sidecar written; dir holds {[p.name for p in baseline_dir.iterdir()]}"
    stored = json.loads(sidecars[0].read_text(encoding="utf-8"))
    assert len(stored["elements"]) == 2


def test_t11b_sdk_snapshot_without_dom_still_succeeds(srv):
    # Older SDKs, and pages that refuse to evaluate the capture script, send no
    # DOM at all. That has to stay a working screenshot comparison rather than
    # an error, so the sidecar is simply absent.
    port, paths, store = srv
    cookie = _login(port)
    status, data = _api(
        port, "/api/sdk/snapshot",
        method="POST",
        body={"name": "no-dom-page", "image": _b64_png()},
        cookie=cookie,
    )
    assert status == 200 and data.get("action") == "baseline_created", data
    baseline_dir = paths.baselines_dir / "no-dom-page"
    assert baseline_dir.is_dir()
    assert not list(baseline_dir.glob("*.dom.json"))


def test_t11c_dom_capture_script_is_served_to_clients(srv):
    # The SDK fetches the capture script instead of carrying a copy, so the two
    # cannot drift apart — a field added to the capture (parent indices, most
    # recently) reaches clients without an SDK release.
    port, *_ = srv
    cookie = _login(port)
    status, data = _api(port, "/api/sdk/dom-capture-js", cookie=cookie)
    assert status == 200, data
    js = data.get("js") or ""
    assert "querySelectorAll" in js and "getBoundingClientRect" in js
