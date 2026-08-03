import socket
import threading
import urllib.request
import urllib.error
import pytest
from http.server import ThreadingHTTPServer

from visual_regression.config import WorkspacePaths
from visual_regression.dashboard_server import DashboardHandler


def get_free_port():
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def test_server(tmp_path):
    project_root = tmp_path
    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    paths.ensure()

    # Create baseline directory and file
    baseline_dir = paths.baselines_dir / "my_test"
    baseline_dir.mkdir(parents=True)
    (baseline_dir / "baseline.png").write_bytes(b"mock_baseline_png")

    # Create run directory and file
    run_dir = paths.runs_dir / "my_run"
    run_dir.mkdir(parents=True)
    (run_dir / "current.png").write_bytes(b"mock_current_png")

    port = get_free_port()

    class TestServer(ThreadingHTTPServer):
        def log_message(self, format, *args):
            pass

    handler_class = lambda *args, **kwargs: DashboardHandler(
        *args, project_root=project_root, paths=paths, port=port, **kwargs
    )

    server = TestServer(("127.0.0.1", port), handler_class)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()

    yield port, paths

    server.shutdown()
    server.server_close()
    thread.join()


def test_static_routes_unauthorized(test_server):
    port, _ = test_server

    # Test /baseline/my_test/baseline.png without auth
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/baseline/my_test/baseline.png")
    assert exc_info.value.code == 403

    # Test /artifacts/my_run/current.png without auth
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/artifacts/my_run/current.png")
    assert exc_info.value.code == 403


def test_health_and_actions_unauthorized(test_server):
    port, _ = test_server

    # 1. Test /api/health (should succeed without auth)
    resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health")
    import json
    data = json.loads(resp.read().decode("utf-8"))
    assert data["ok"] is True
    assert data["status"] == "healthy"

    # 2. Test /api/actions/create-demo-baselines (should fail with 403 without auth)
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/actions/create-demo-baselines",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 403


def test_dashboard_actions(test_server):
    import json
    from unittest.mock import patch
    import subprocess
    from visual_regression.sqlite_store import SqliteStore

    port, paths = test_server
    store = SqliteStore(paths.db_path)
    store.ensure_bootstrap_users()

    # Log in to get session cookie
    login_url = f"http://127.0.0.1:{port}/api/auth/login"
    login_data = json.dumps({"email": "admin", "password": "admin1234"}).encode("utf-8")
    req = urllib.request.Request(login_url, data=login_data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        cookie = resp.getheader("Set-Cookie", "")
        cookie_val = ""
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("lens_session="):
                cookie_val = part
                break

    assert cookie_val != ""

    mock_process = subprocess.CompletedProcess(args=[], returncode=0, stdout="mock success", stderr="")
    
    with patch("subprocess.run", return_value=mock_process) as mock_run:
        # 1. Test create-baseline
        payload = {
            "name": "test-b1",
            "url": "http://127.0.0.1/page",
            "browser": "Chrome",
            "device": "Desktop",
            "locale": "zh-CN"
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/actions/create-baseline",
            data=json.dumps(payload).encode("utf-8"),
            method="POST"
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Cookie", cookie_val)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
            assert data["stdout"] == "mock success"
        
        mock_run.assert_called_once()
        called_args = mock_run.call_args[0][0]
        assert "create-baseline" in called_args
        assert "test-b1" in called_args
        assert "chromium" in called_args
        assert "zh-CN" in called_args
        assert "--device" not in called_args
        mock_run.reset_mock()

        # 2. Test create-multiple-baselines
        payload = {
            "url": "http://127.0.0.1/site",
            "browser": "Safari",
            "overwrite": True
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/actions/create-multiple-baselines",
            data=json.dumps(payload).encode("utf-8"),
            method="POST"
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Cookie", cookie_val)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
        
        mock_run.assert_called_once()
        called_args = mock_run.call_args[0][0]
        assert "create-multiple-baselines" in called_args
        assert "webkit" in called_args
        assert "--overwrite" in called_args
        mock_run.reset_mock()

        # 3. Test update-baseline (Sync & Replace old/new format)
        payload = {
            "old": "test-b1",
            "new": "test-b2"
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/actions/update-baseline",
            data=json.dumps(payload).encode("utf-8"),
            method="POST"
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Cookie", cookie_val)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
        
        mock_run.assert_called_once()
        called_args = mock_run.call_args[0][0]
        assert "update-baseline" in called_args
        assert "test-b1" in called_args
        image_arg_idx = called_args.index("--image")
        assert "test-b2" in called_args[image_arg_idx + 1]
        mock_run.reset_mock()

        # 4. Test compare
        payload = {
            "name": "test-b1",
            "url": "http://127.0.0.1/check",
            "browsers": ["Chrome"],
            "devices": ["Desktop"],
            "locales": ["en-US"],
            "login_url": "http://127.0.0.1/login",
            "login_username": "myuser",
            "login_password": "mypassword",
            "username_selector": "#user",
            "password_selector": "#pass",
            "submit_selector": "#btn"
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/actions/compare",
            data=json.dumps(payload).encode("utf-8"),
            method="POST"
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Cookie", cookie_val)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
        
        mock_run.assert_called_once()
        called_args = mock_run.call_args[0][0]
        assert "compare" in called_args
        assert "chromium" in called_args
        assert "--login-url" in called_args
        assert "http://127.0.0.1/login" in called_args
        assert "--login-username" in called_args
        assert "myuser" in called_args
        assert "--login-password" in called_args
        assert "mypassword" in called_args
        assert "--username-selector" in called_args
        assert "#user" in called_args
        assert "--password-selector" in called_args
        assert "#pass" in called_args
        assert "--submit-selector" in called_args
        assert "#btn" in called_args
        mock_run.reset_mock()

        # 5. Test compare matrix
        payload = {
            "name": "test-b1",
            "url": "http://127.0.0.1/check",
            "browsers": ["Chrome", "Safari"],
            "devices": ["Desktop", "iPhone 13"],
            "locales": ["en-US"],
            "login_url": "http://127.0.0.1/login",
            "login_username": "myuser",
            "login_password": "mypassword",
            "username_selector": "#user",
            "password_selector": "#pass",
            "submit_selector": "#btn"
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/actions/compare",
            data=json.dumps(payload).encode("utf-8"),
            method="POST"
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Cookie", cookie_val)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
        
        mock_run.assert_called_once()
        called_args = mock_run.call_args[0][0]
        assert "compare-matrix" in called_args
        assert "chromium" in called_args
        assert "webkit" in called_args
        assert "iPhone 13" in called_args
        assert "--device" in called_args
        assert "--login-url" in called_args
        assert "http://127.0.0.1/login" in called_args
        assert "--login-username" in called_args
        assert "myuser" in called_args
        assert "--login-password" in called_args
        assert "mypassword" in called_args
        assert "--username-selector" in called_args
        assert "#user" in called_args
        assert "--password-selector" in called_args
        assert "#pass" in called_args
        assert "--submit-selector" in called_args
        assert "#btn" in called_args


def test_comments_api(test_server):
    import json
    from visual_regression.database import get_store

    port, paths = test_server
    store = get_store(paths.db_path)
    store.ensure_bootstrap_users()

    # Log in
    login_url = f"http://127.0.0.1:{port}/api/auth/login"
    login_data = json.dumps({"email": "admin", "password": "admin1234"}).encode("utf-8")
    req = urllib.request.Request(login_url, data=login_data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        cookie = resp.getheader("Set-Cookie", "")
        cookie_val = ""
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("lens_session="):
                cookie_val = part
                break

    assert cookie_val != ""

    # Insert a dummy run to satisfy foreign key constraints
    dummy_run = {
        "run": "test-run-123",
        "case_name": "Test Case 1",
        "baseline_name": "test-b1",
        "suite_name": "suite.demo",
        "status": "fail",
        "mismatch_pct": 1.2,
        "diff_regions": 1,
        "browser": "chromium",
        "device": "desktop",
        "locale": "en-US",
        "url": "http://example.com",
        "report_href": "/report",
    }
    store.upsert_run_index(dummy_run)

    # 1. Create Comment
    payload = {
        "run_id": "test-run-123",
        "x_pct": 25.5,
        "y_pct": 50.0,
        "content": "This button is misaligned."
    }
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/comments/create",
        data=json.dumps(payload).encode("utf-8"),
        method="POST"
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Cookie", cookie_val)
    
    comment_id = ""
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert data["ok"] is True
        assert "comment_id" in data
        comment_id = data["comment_id"]

    assert comment_id != ""

    # 2. Get Comments
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/comments?run_id=test-run-123",
        method="GET"
    )
    req.add_header("Cookie", cookie_val)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert data["ok"] is True
        comments = data["comments"]
        assert len(comments) == 1
        assert comments[0]["id"] == comment_id
        assert comments[0]["content"] == "This button is misaligned."
        assert comments[0]["author"] == "admin"
        assert abs(comments[0]["x_pct"] - 25.5) < 0.01

    # 3. Delete Comment
    payload = {
        "comment_id": comment_id
    }
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/comments/delete",
        data=json.dumps(payload).encode("utf-8"),
        method="POST"
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Cookie", cookie_val)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert data["ok"] is True

    # 4. Confirm Deleted
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/comments?run_id=test-run-123",
        method="GET"
    )
    req.add_header("Cookie", cookie_val)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert len(data["comments"]) == 0


def test_ai_suggestions_api(test_server):
    import json
    from visual_regression.database import get_store

    port, paths = test_server
    store = get_store(paths.db_path)
    store.ensure_bootstrap_users()

    # Log in
    login_url = f"http://127.0.0.1:{port}/api/auth/login"
    login_data = json.dumps({"email": "admin", "password": "admin1234"}).encode("utf-8")
    req = urllib.request.Request(login_url, data=login_data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        cookie = resp.getheader("Set-Cookie", "")
        cookie_val = ""
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("lens_session="):
                cookie_val = part
                break

    assert cookie_val != ""

    # Create 3 failed runs for a baseline in the database and disk

    # Run 1
    dummy_run_1 = {
        "run": "run-f1",
        "case_name": "Case Auto",
        "baseline_name": "baseline-auto",
        "suite_name": "suite.auto",
        "status": "FAIL",
        "mismatch_pct": 2.5,
        "diff_regions": 1,
        "browser": "chromium",
        "device": "desktop",
        "locale": "en-US",
        "url": "http://example.com",
        "report_href": "/report1",
    }
    store.upsert_run_index(dummy_run_1)
    # Save payload to disk
    run_dir_1 = paths.runs_dir / "run-f1"
    run_dir_1.mkdir(parents=True, exist_ok=True)
    payload_1 = {
        "id": "run-f1",
        "baseline_name": "baseline-auto",
        "case_name": "Case Auto",
        "status": "FAIL",
        "result": {
            "mismatch_pct": 2.5,
            "regions": [
                {"x": 100, "y": 200, "width": 50, "height": 30, "mean_delta": 60.0}
            ]
        }
    }
    with open(run_dir_1 / "result.json", "w") as f:
        json.dump(payload_1, f)

    # Run 2
    dummy_run_2 = {
        "run": "run-f2",
        "case_name": "Case Auto",
        "baseline_name": "baseline-auto",
        "suite_name": "suite.auto",
        "status": "FAIL",
        "mismatch_pct": 3.0,
        "diff_regions": 1,
        "browser": "chromium",
        "device": "desktop",
        "locale": "en-US",
        "url": "http://example.com",
        "report_href": "/report2",
    }
    store.upsert_run_index(dummy_run_2)
    # Save payload to disk (overlaps with run 1 region [100, 200, 50, 30])
    run_dir_2 = paths.runs_dir / "run-f2"
    run_dir_2.mkdir(parents=True, exist_ok=True)
    payload_2 = {
        "id": "run-f2",
        "baseline_name": "baseline-auto",
        "case_name": "Case Auto",
        "status": "FAIL",
        "result": {
            "mismatch_pct": 3.0,
            "regions": [
                {"x": 102, "y": 198, "width": 48, "height": 32, "mean_delta": 55.0}
            ]
        }
    }
    with open(run_dir_2 / "result.json", "w") as f:
        json.dump(payload_2, f)

    # Request AI suggestions for a new run
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/ai-suggestions?baseline_name=baseline-auto&run_id=run-f3",
        method="GET"
    )
    req.add_header("Cookie", cookie_val)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        assert data["ok"] is True
        suggestions = data["suggestions"]
        assert len(suggestions) == 1
        # The suggestion should envelop both overlapping boxes
        # min_x = min(100, 102) = 100
        # min_y = min(200, 198) = 198
        # max_r = max(150, 150) = 150 => width = 150 - 100 = 50
        # max_b = max(230, 230) = 230 => height = 230 - 198 = 32
        assert suggestions[0]["x"] == 100
        assert suggestions[0]["y"] == 198
        assert suggestions[0]["width"] == 50
        assert suggestions[0]["height"] == 32
        assert suggestions[0]["frequency"] == 2


def test_review_action_updates_runs_index(test_server):
    """Regression test: approving/rejecting a run must update the SQLite
    runs_index table, not just the on-disk result.json. result.json has no
    top-level "run"/"run_id" key of its own, so passing it straight to
    store.upsert_run_index() without adding run_id makes the upsert silently
    no-op (empty run_id -> early return) — the dashboard's stats/filters
    then never reflect a review that actually happened."""
    import json as json_mod
    from visual_regression.sqlite_store import SqliteStore

    port, paths = test_server
    store = SqliteStore(paths.db_path)
    store.ensure_bootstrap_users()

    run_id = "reviewable-run"
    run_dir = paths.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    result_payload = {
        "case_name": "demo",
        "baseline_name": "demo",
        "suite_name": None,
        "status": "FAIL",
        "result": {
            "baseline_size": [100, 100], "current_size": [100, 100],
            "diff_pixels": 10, "total_pixels": 10000, "mismatch_pct": 2.5,
            "ssim_score": 0.9, "regions": [],
        },
        "decision": {"status": "pending"},
        "ai_assessment": {},
        "severity": {"label": "medium"},
        "capture": {"url": "https://example.com", "browser": "chromium", "device": "desktop", "locale": "en-US"},
    }
    (run_dir / "result.json").write_text(json_mod.dumps(result_payload), encoding="utf-8")
    # Seed runs_index the way a normal run would — decision_status starts unreviewed.
    store.upsert_run_index({
        "run_id": run_id, "case_name": "demo", "baseline_name": "demo", "suite_name": None,
        "status": "FAIL", "mismatch_pct": 2.5, "diff_regions": 0, "decision_status": "pending",
        "decided_at": "", "severity_label": "medium", "ai_label": None,
        "browser": "chromium", "device": "desktop", "locale": "en-US", "url": "https://example.com",
        "report_href": f"/artifacts/{run_id}/report.html", "decider": "", "decision_comment": "", "ai_score": None,
    })

    login_url = f"http://127.0.0.1:{port}/api/auth/login"
    login_data = json_mod.dumps({"email": "admin", "password": "admin1234"}).encode("utf-8")
    req = urllib.request.Request(login_url, data=login_data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        cookie = resp.getheader("Set-Cookie", "")
        cookie_val = next((p.strip() for p in cookie.split(";") if p.strip().startswith("lens_session=")), "")
    assert cookie_val != ""

    review_req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/actions/review",
        data=json_mod.dumps({"run": run_id, "decision": "approved", "comment": "looks fine"}).encode("utf-8"),
        method="POST",
    )
    review_req.add_header("Content-Type", "application/json")
    review_req.add_header("Cookie", cookie_val)
    with urllib.request.urlopen(review_req) as resp:
        data = json_mod.loads(resp.read().decode("utf-8"))
        assert data.get("ok") is True

    # The bug: without this fix, decision_status stays "pending" in the DB
    # even though result.json on disk correctly says "approved".
    row = store._connect().execute(
        "SELECT decision_status, decider, decision_comment FROM runs_index WHERE run_id = ?", (run_id,)
    ).fetchone()
    assert row is not None, "run_id was never written to runs_index"
    assert row["decision_status"] == "approved"
    assert row["decider"] == "admin"
    assert row["decision_comment"] == "looks fine"


def test_bulk_review_action_updates_runs_index(test_server):
    """Same bug as test_review_action_updates_runs_index, but for the bulk
    endpoint: manager.load_run_payload(run_dir) returns result.json's raw
    content, which has no "run"/"run_id" key. bulk_insert_runs() filters out
    any row whose run_id is empty, so without adding run_id explicitly the
    whole batch silently disappears (API still reports success=True per run)."""
    import json as json_mod
    from visual_regression.sqlite_store import SqliteStore

    port, paths = test_server
    store = SqliteStore(paths.db_path)
    store.ensure_bootstrap_users()

    run_ids = ["bulk-run-a", "bulk-run-b"]
    for run_id in run_ids:
        run_dir = paths.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        result_payload = {
            "case_name": "demo", "baseline_name": "demo", "suite_name": None, "status": "FAIL",
            "result": {
                "baseline_size": [100, 100], "current_size": [100, 100],
                "diff_pixels": 10, "total_pixels": 10000, "mismatch_pct": 2.5,
                "ssim_score": 0.9, "regions": [],
            },
            "decision": {"status": "pending"},
            "ai_assessment": {},
            "severity": {"label": "medium"},
            "capture": {"url": "https://example.com", "browser": "chromium", "device": "desktop", "locale": "en-US"},
        }
        (run_dir / "result.json").write_text(json_mod.dumps(result_payload), encoding="utf-8")
        store.upsert_run_index({
            "run_id": run_id, "case_name": "demo", "baseline_name": "demo", "suite_name": None,
            "status": "FAIL", "mismatch_pct": 2.5, "diff_regions": 0, "decision_status": "pending",
            "decided_at": "", "severity_label": "medium", "ai_label": None,
            "browser": "chromium", "device": "desktop", "locale": "en-US", "url": "https://example.com",
            "report_href": f"/artifacts/{run_id}/report.html", "decider": "", "decision_comment": "", "ai_score": None,
        })

    login_url = f"http://127.0.0.1:{port}/api/auth/login"
    login_data = json_mod.dumps({"email": "admin", "password": "admin1234"}).encode("utf-8")
    req = urllib.request.Request(login_url, data=login_data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        cookie = resp.getheader("Set-Cookie", "")
        cookie_val = next((p.strip() for p in cookie.split(";") if p.strip().startswith("lens_session=")), "")
    assert cookie_val != ""

    bulk_req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/bulk-review",
        data=json_mod.dumps({"runs": run_ids, "decision": "rejected", "comment": "bulk test"}).encode("utf-8"),
        method="POST",
    )
    bulk_req.add_header("Content-Type", "application/json")
    bulk_req.add_header("Cookie", cookie_val)
    with urllib.request.urlopen(bulk_req) as resp:
        data = json_mod.loads(resp.read().decode("utf-8"))
        assert data.get("ok") is True
        assert all(r["success"] for r in data["results"])

    conn = store._connect()
    for run_id in run_ids:
        row = conn.execute(
            "SELECT decision_status, decider FROM runs_index WHERE run_id = ?", (run_id,)
        ).fetchone()
        assert row is not None, f"{run_id} was never written to runs_index"
        assert row["decision_status"] == "rejected"
        assert row["decider"] == "admin"


def test_api_endpoints_unauthorized(test_server):
    port, _ = test_server

    # 1. Test GET /api/dashboard without auth -> should return 401
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/dashboard")
    assert exc_info.value.code == 401

    # 2. Test GET /api/baseline without auth -> should return 401
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/baseline?id=test")
    assert exc_info.value.code == 401

    # 3. Test POST /api/scheduler/jobs without auth -> should return 403
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/scheduler/jobs",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req)
    assert exc_info.value.code == 403





