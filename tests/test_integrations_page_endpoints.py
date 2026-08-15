"""The Integrations page's remaining endpoints, over HTTP.

GitHub OAuth, webhook URL validation and token encryption were already
covered. These three were not: the "Send test" button, the activity feed it
writes to, and the API key controls. The key ones matter most — rotating is
the only way to revoke the credential every SDK client authenticates with, and
nothing verified that the old key actually stops working afterwards.
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


def _login(port, email="admin", password="admin1234"):
    data = json.dumps({"email": email, "password": password}).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/auth/login", data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        for part in resp.getheader("Set-Cookie", "").split(";"):
            part = part.strip()
            if part.startswith("lens_session="):
                return part
    raise AssertionError("login did not set a session cookie")


def _call(port, path, *, method="GET", cookie=None, body=None, headers=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", cookie)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"raw": raw}


class TestSendTestWebhook:
    """The button that tells an admin their webhook works."""

    def test_a_reachable_endpoint_reports_success(self, server, monkeypatch):
        port, _, _ = server
        from visual_regression import notifier

        sent = []
        monkeypatch.setattr(
            notifier, "trigger_webhook_detailed", lambda url, payload: sent.append((url, payload)) or {"ok": True}
        )

        status, body = _call(
            port, "/api/integrations/test-webhook", method="POST",
            cookie=_login(port), body={"url": "https://hooks.example.com/x"},
        )

        assert status == 200 and body["ok"] is True
        assert sent[0][0] == "https://hooks.example.com/x"
        assert sent[0][1]["event"] == "test_ping"

    def test_a_failing_endpoint_is_reported_as_an_error(self, server, monkeypatch):
        port, _, _ = server
        from visual_regression import notifier

        monkeypatch.setattr(notifier, "trigger_webhook_detailed", lambda url, payload: {"ok": False, "error": "500"})

        status, _ = _call(
            port, "/api/integrations/test-webhook", method="POST",
            cookie=_login(port), body={"url": "https://hooks.example.com/x"},
        )

        assert status == 400

    def test_a_loopback_url_is_refused(self, server):
        """SSRF: the server would be asking itself, or something behind it."""
        port, _, _ = server

        status, _ = _call(
            port, "/api/integrations/test-webhook", method="POST",
            cookie=_login(port), body={"url": "http://127.0.0.1:9/x"},
        )

        assert status == 400

    def test_an_empty_url_is_refused(self, server):
        port, _, _ = server

        status, _ = _call(
            port, "/api/integrations/test-webhook", method="POST", cookie=_login(port), body={"url": ""}
        )

        assert status == 400

    def test_a_developer_may_not_send_one(self, server, monkeypatch):
        port, _, store = server
        from visual_regression import notifier

        sent = []
        monkeypatch.setattr(notifier, "trigger_webhook_detailed", lambda url, payload: sent.append(url) or {"ok": True})
        store.create_user("dev@example.com", "password123", "developer")

        status, _ = _call(
            port, "/api/integrations/test-webhook", method="POST",
            cookie=_login(port, "dev@example.com", "password123"),
            body={"url": "https://hooks.example.com/x"},
        )

        assert status == 403
        assert sent == []


class TestActivityFeed:
    def test_a_webhook_test_shows_up_in_the_feed(self, server, monkeypatch):
        port, _, _ = server
        from visual_regression import notifier

        monkeypatch.setattr(notifier, "trigger_webhook_detailed", lambda url, payload: {"ok": True})
        cookie = _login(port)

        _call(port, "/api/integrations/test-webhook", method="POST", cookie=cookie,
              body={"url": "https://hooks.example.com/x"})
        status, body = _call(port, "/api/integrations/activity", cookie=cookie)

        assert status == 200
        assert any("Webhook test succeeded" in str(entry) for entry in body["activity"])

    def test_the_feed_requires_a_session(self, server):
        port, _, _ = server

        status, _ = _call(port, "/api/integrations/activity")

        assert status == 401


class TestApiKey:
    """The key an SDK client authenticates with, via the X-Access-Key header.

    /artifacts is the surface it opens: an authorised client reaching a missing
    file gets a 404, an unauthorised one never gets that far and gets a 403.
    """

    ARTIFACT = "/artifacts/no-such-run/current.webp"

    def _reveal(self, port, cookie):
        return _call(port, "/api/integrations/reveal-key", method="POST", cookie=cookie)[1]["api_key"]

    def test_the_revealed_key_authenticates_an_api_client(self, server):
        port, _, _ = server
        cookie = _login(port)
        key = self._reveal(port, cookie)

        status, _ = _call(port, self.ARTIFACT, headers={"X-Access-Key": key})

        assert status == 404

    def test_a_wrong_key_does_not(self, server):
        port, _, _ = server

        status, _ = _call(port, self.ARTIFACT, headers={"X-Access-Key": "not-the-key"})

        assert status == 403

    def test_no_key_at_all_does_not(self, server):
        port, _, _ = server

        status, _ = _call(port, self.ARTIFACT)

        assert status == 403

    def test_rotating_returns_a_different_key(self, server):
        port, _, _ = server
        cookie = _login(port)
        before = self._reveal(port, cookie)

        after = _call(port, "/api/integrations/rotate-key", method="POST", cookie=cookie)[1]["api_key"]

        assert after and after != before
        assert self._reveal(port, cookie) == after

    def test_the_old_key_stops_working_immediately(self, server):
        """The cached key used to keep authorising for the cache TTL after the
        rotation that was supposed to revoke it."""
        port, _, _ = server
        cookie = _login(port)
        old_key = self._reveal(port, cookie)
        # Warm the key cache so the rotation has something stale to clear.
        _call(port, self.ARTIFACT, headers={"X-Access-Key": old_key})

        _call(port, "/api/integrations/rotate-key", method="POST", cookie=cookie)

        status, _ = _call(port, self.ARTIFACT, headers={"X-Access-Key": old_key})
        assert status == 403

    def test_the_new_key_works_immediately(self, server):
        port, _, _ = server
        cookie = _login(port)

        new_key = _call(port, "/api/integrations/rotate-key", method="POST", cookie=cookie)[1]["api_key"]

        status, _ = _call(port, self.ARTIFACT, headers={"X-Access-Key": new_key})
        assert status == 404

    def test_a_developer_may_not_reveal_or_rotate(self, server):
        port, _, store = server
        store.create_user("dev2@example.com", "password123", "developer")
        dev_cookie = _login(port, "dev2@example.com", "password123")

        reveal_status, _ = _call(port, "/api/integrations/reveal-key", method="POST", cookie=dev_cookie)
        rotate_status, _ = _call(port, "/api/integrations/rotate-key", method="POST", cookie=dev_cookie)

        assert reveal_status == 403
        assert rotate_status == 403
