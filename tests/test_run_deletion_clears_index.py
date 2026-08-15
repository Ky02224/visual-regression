"""Deleting a run has to remove it from the index too.

Deleting removed the run's directory and left its runs_index row behind, so
the dashboard went on listing a run whose every image answered 404 — and
nothing in the product could clear it. Thirteen such rows had accumulated in
the development workspace before anyone traced the broken thumbnails to it.
"""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request

import pytest
import uvicorn

from visual_regression.config import WorkspacePaths
from visual_regression.database import get_store
from visual_regression.sqlite_store import SqliteStore


class TestStoreDelete:
    @pytest.fixture
    def store(self, tmp_path):
        store = SqliteStore(tmp_path / "storage.db")
        store.upsert_run_index({
            "run_id": "run-1", "case_name": "home", "baseline_name": "home",
            "status": "FAIL", "created_at": 1,
        })
        return store

    def test_the_row_is_gone(self, store):
        store.delete_run_index("run-1")

        assert store.get_run_index("run-1") is None

    def test_its_comments_go_with_it(self, store):
        """They carry a foreign key to the run row, so leaving them would
        either fail the delete or orphan them."""
        store.add_comment("c1", "run-1", 0.0, 0.0, "a@b.com", "look here")

        store.delete_run_index("run-1")

        assert store.count_comments_by_run() == {}

    def test_other_runs_are_untouched(self, store):
        store.upsert_run_index({
            "run_id": "run-2", "case_name": "home", "baseline_name": "home",
            "status": "PASS", "created_at": 2,
        })

        store.delete_run_index("run-1")

        assert store.get_run_index("run-2") is not None

    def test_deleting_an_unknown_run_is_not_an_error(self, store):
        store.delete_run_index("never-existed")

        assert store.get_run_index("run-1") is not None


def _free_port():
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def server(tmp_path):
    from visual_regression import dashboard_server

    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    paths.ensure()
    store = get_store(paths.db_path)
    store.ensure_bootstrap_users()

    run_dir = paths.runs_dir / "run-to-delete"
    run_dir.mkdir(parents=True)
    (run_dir / "result.json").write_text(json.dumps({"id": "run-to-delete", "status": "FAIL"}), encoding="utf-8")
    store.upsert_run_index({
        "run_id": "run-to-delete", "case_name": "home", "baseline_name": "home",
        "status": "FAIL", "created_at": 1,
    })

    app = dashboard_server.app
    app.state.paths = paths
    app.state.store = store
    app.state.project_root = tmp_path
    port = _free_port()
    app.state.port = port

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    uvicorn_server = uvicorn.Server(config)
    thread = threading.Thread(target=uvicorn_server.run, daemon=True)
    thread.start()
    for _ in range(200):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1).read()
            break
        except Exception:
            threading.Event().wait(0.05)

    yield port, paths, store

    uvicorn_server.should_exit = True
    thread.join(timeout=10)


def _login(port):
    data = json.dumps({"email": "admin", "password": "admin1234"}).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/auth/login", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        for part in resp.getheader("Set-Cookie", "").split(";"):
            part = part.strip()
            if part.startswith("lens_session="):
                return part
    raise AssertionError("login did not set a session cookie")


def _call(port, path, *, method="GET", cookie=None, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, {}


class TestDeleteEndpoint:
    def test_the_deleted_run_disappears_from_the_dashboard(self, server):
        port, _, _ = server
        cookie = _login(port)
        before = _call(port, "/api/dashboard", cookie=cookie)[1]["runs"]
        assert any(r["id"] == "run-to-delete" for r in before)

        status, _ = _call(port, "/api/run/delete", method="POST", cookie=cookie, body={"run": "run-to-delete"})

        assert status == 200
        after = _call(port, "/api/dashboard", cookie=cookie)[1]["runs"]
        assert not any(r["id"] == "run-to-delete" for r in after)

    def test_the_files_are_gone_too(self, server):
        port, paths, _ = server

        _call(port, "/api/run/delete", method="POST", cookie=_login(port), body={"run": "run-to-delete"})

        assert not (paths.runs_dir / "run-to-delete").exists()

    def test_the_index_row_is_gone(self, server):
        port, _, store = server

        _call(port, "/api/run/delete", method="POST", cookie=_login(port), body={"run": "run-to-delete"})

        assert store.get_run_index("run-to-delete") is None
