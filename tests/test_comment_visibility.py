"""A comment has to be visible from outside the report page it lives on.

Two paths carry it: the dashboard snapshot gains a per-run count so the run
lists can badge it, and a configured webhook gets told. Both are wired at the
HTTP layer, which is where the cache and the notifier can quietly not happen.
"""

from __future__ import annotations

import json
import socket
import threading
import urllib.request

import pytest
import uvicorn

from visual_regression.config import WorkspacePaths
from visual_regression.database import get_store


def _free_port():
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def server(tmp_path):
    """The real ASGI app over a real socket, on its own workspace."""
    from visual_regression import dashboard_server

    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    paths.ensure()
    store = get_store(paths.db_path)
    store.ensure_bootstrap_users()
    store.upsert_run_index({
        "run": "run-a",
        "case_name": "checkout",
        "baseline_name": "checkout",
        "status": "FAIL",
        "mismatch_pct": 2.0,
        "created_at": 10,
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


def _login(port: str) -> str:
    data = json.dumps({"email": "admin", "password": "admin1234"}).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/auth/login", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        for part in resp.getheader("Set-Cookie", "").split(";"):
            part = part.strip()
            if part.startswith("lens_session="):
                return part
    raise AssertionError("login did not set a session cookie")


def _post(port, cookie, path, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode("utf-8"), method="POST"
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Cookie", cookie)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(port, cookie, path):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="GET")
    req.add_header("Cookie", cookie)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _run_row(snapshot, run_id):
    return next(r for r in snapshot["runs"] if r["id"] == run_id)


class TestDashboardBadge:
    def test_a_run_without_comments_reports_zero(self, server):
        port, _, _ = server
        cookie = _login(port)

        assert _run_row(_get(port, cookie, "/api/dashboard"), "run-a")["comment_count"] == 0

    def test_the_count_appears_after_commenting(self, server):
        port, _, _ = server
        cookie = _login(port)
        _get(port, cookie, "/api/dashboard")  # prime the 60s snapshot cache

        _post(port, cookie, "/api/comments/create", {"run_id": "run-a", "content": "look here"})
        _post(port, cookie, "/api/comments/create", {"run_id": "run-a", "content": "and here"})

        # Without the cache invalidation this still reads 0 for a minute.
        assert _run_row(_get(port, cookie, "/api/dashboard"), "run-a")["comment_count"] == 2

    def test_the_count_drops_again_when_a_comment_is_deleted(self, server):
        port, _, _ = server
        cookie = _login(port)
        created = _post(port, cookie, "/api/comments/create", {"run_id": "run-a", "content": "x"})
        _get(port, cookie, "/api/dashboard")

        _post(port, cookie, "/api/comments/delete", {"comment_id": created["comment_id"]})

        assert _run_row(_get(port, cookie, "/api/dashboard"), "run-a")["comment_count"] == 0


class TestWebhook:
    def test_a_new_comment_is_announced(self, server, monkeypatch):
        port, paths, _ = server
        from visual_regression import notifier
        from visual_regression.integrations_manager import IntegrationsManager

        IntegrationsManager(paths.root).update_webhook("https://hooks.example.com/abc", 0.0)
        sent = []
        monkeypatch.setattr(
            notifier, "trigger_webhook_detailed", lambda url, payload: sent.append((url, payload)) or {"ok": True}
        )
        cookie = _login(port)

        _post(port, cookie, "/api/comments/create", {"run_id": "run-a", "content": "please check the header"})

        assert len(sent) == 1
        url, payload = sent[0]
        assert url == "https://hooks.example.com/abc"
        assert payload["event"] == "comment.added"
        assert payload["case_name"] == "checkout"
        assert payload["content"] == "please check the header"

    def test_nothing_is_sent_when_no_webhook_is_configured(self, server, monkeypatch):
        port, _, _ = server
        from visual_regression import notifier

        sent = []
        monkeypatch.setattr(
            notifier, "trigger_webhook_detailed", lambda url, payload: sent.append(url) or {"ok": True}
        )
        cookie = _login(port)

        _post(port, cookie, "/api/comments/create", {"run_id": "run-a", "content": "x"})

        assert sent == []

    def test_an_unreachable_webhook_does_not_lose_the_comment(self, server, monkeypatch):
        """The reviewer already wrote it; a dead endpoint is not their problem."""
        port, paths, store = server
        from visual_regression import notifier
        from visual_regression.integrations_manager import IntegrationsManager

        IntegrationsManager(paths.root).update_webhook("https://hooks.example.com/abc", 0.0)

        def explode(url, payload):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(notifier, "trigger_webhook_detailed", explode)
        cookie = _login(port)

        result = _post(port, cookie, "/api/comments/create", {"run_id": "run-a", "content": "still saved"})

        assert result["ok"] is True
        assert [c["content"] for c in store.list_comments("run-a")] == ["still saved"]
