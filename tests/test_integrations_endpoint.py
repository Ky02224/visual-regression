"""GET /api/integrations used to return the webhook URL in full to *any*
authenticated user (require_auth, not require_admin) — while the API key at
the same endpoint was properly masked. A Slack/Discord/Teams webhook URL is
itself a bearer credential (anyone holding it can post as the integration),
so a viewer/developer could read it straight off this endpoint even though
every endpoint that *mutates* it already correctly required admin.
"""
import json
import socket
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from visual_regression.config import WorkspacePaths
from visual_regression.dashboard_server import DashboardHandler
from visual_regression.integrations_manager import IntegrationsManager
from visual_regression.sqlite_store import SqliteStore


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

    manager = IntegrationsManager(paths.root)
    manager.update_webhook("https://hooks.slack.com/services/T00/B00/super-secret-token", threshold=1.0)

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


def _login_cookie(port: int, paths: WorkspacePaths, email: str, password: str) -> str:
    store = SqliteStore(paths.db_path)
    store.ensure_bootstrap_users()

    login_url = f"http://127.0.0.1:{port}/api/auth/login"
    login_data = json.dumps({"email": email, "password": password}).encode("utf-8")
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
    return cookie_val


def _get_integrations(port: int, cookie: str) -> dict:
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/integrations")
    req.add_header("Cookie", cookie)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_admin_sees_full_webhook_url(test_server):
    port, paths = test_server
    cookie = _login_cookie(port, paths, "admin", "admin1234")

    data = _get_integrations(port, cookie)

    assert data["webhook_url"] == "https://hooks.slack.com/services/T00/B00/super-secret-token"
    assert data["webhook_connected"] is True


def test_developer_does_not_see_webhook_url(test_server):
    port, paths = test_server
    cookie = _login_cookie(port, paths, "user", "user1234")

    data = _get_integrations(port, cookie)

    assert data["webhook_url"] == ""
    # The non-secret "is something configured" signal is still available.
    assert data["webhook_connected"] is True
