"""Regression coverage for /api/users* — in particular, that demoting or
disabling the last admin via /api/users/update is blocked the same way
/api/users/delete already blocks deleting the last admin. Before this fix,
POST /api/users/update {"email": "admin", "role": "viewer"} succeeded even
when "admin" was the only admin account, which locks the whole team out of
every user-management endpoint (they're all gated by require_admin) with no
recovery path short of editing the database directly.
"""
import json
import socket
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from visual_regression.config import WorkspacePaths
from visual_regression.dashboard_server import DashboardHandler
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


def _admin_cookie(port: int, paths: WorkspacePaths) -> str:
    store = SqliteStore(paths.db_path)
    store.ensure_bootstrap_users()

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
    return cookie_val


def _post(port, path, cookie, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _get_roles(port, cookie):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/users")
    req.add_header("Cookie", cookie)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return {u["email"]: u["role"] for u in data["users"]}


def test_demoting_last_admin_is_blocked(test_server):
    port, paths = test_server
    cookie = _admin_cookie(port, paths)

    status, data = _post(port, "/api/users/update", cookie, {"email": "admin", "role": "viewer"})
    assert status == 400
    assert data["ok"] is False or "detail" in data

    # Confirm the account is still admin, and the admin session can still
    # manage users afterward (no lockout occurred).
    assert _get_roles(port, cookie)["admin"] == "admin"


def test_disabling_last_admin_is_blocked(test_server):
    port, paths = test_server
    cookie = _admin_cookie(port, paths)

    status, _ = _post(port, "/api/users/update", cookie, {"email": "admin", "disabled": True})
    assert status == 400
    assert _get_roles(port, cookie)["admin"] == "admin"


def test_demoting_non_last_admin_is_allowed(test_server):
    port, paths = test_server
    cookie = _admin_cookie(port, paths)

    # Create a second admin so "admin" is no longer the last one.
    status, _ = _post(port, "/api/users", cookie, {
        "email": "second-admin@example.com", "password": "S3cure!Pass123", "role": "admin", "name": "Second Admin",
    })
    assert status == 200

    status, _ = _post(port, "/api/users/update", cookie, {"email": "admin", "role": "viewer"})
    assert status == 200

    # "admin"'s own cookie is no longer privileged after demoting itself —
    # check the result through the still-admin second account instead.
    store = SqliteStore(paths.db_path)
    users = {u["email"]: u["role"] for u in store.list_users()}
    assert users["admin"] == "viewer"
    assert users["second-admin@example.com"] == "admin"


def test_role_change_for_non_admin_is_unaffected(test_server):
    port, paths = test_server
    cookie = _admin_cookie(port, paths)

    status, _ = _post(port, "/api/users/update", cookie, {"email": "user", "role": "viewer"})
    assert status == 200
    assert _get_roles(port, cookie)["user"] == "viewer"


def test_deleting_last_admin_is_still_blocked(test_server):
    """Sanity check the pre-existing delete-side protection this fix mirrors."""
    port, paths = test_server
    cookie = _admin_cookie(port, paths)

    status, _ = _post(port, "/api/users/delete", cookie, {"email": "admin"})
    assert status == 400
