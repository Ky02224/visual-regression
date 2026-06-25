import socket
import threading
import urllib.request
import urllib.error
import pytest
from pathlib import Path
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

