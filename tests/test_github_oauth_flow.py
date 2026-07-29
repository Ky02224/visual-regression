"""End-to-end test of the GitHub OAuth connect/callback flow, driven through
real HTTP requests against the actual FastAPI app (via DashboardHandler's
ASGI bridge), exactly as a browser would hit it. Only the two outbound calls
to github.com (token exchange + user lookup) are mocked, since a real
GitHub OAuth App's client id/secret aren't available in CI/dev.
"""
import json
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

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
def test_server(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GITHUB_OAUTH_CLIENT_SECRET", "test-client-secret")

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


class _NoRedirect(urllib.request.HTTPErrorProcessor):
    def http_response(self, request, response):
        return response

    https_response = http_response


def _opener():
    return urllib.request.build_opener(_NoRedirect)


def test_github_status_reports_configured(test_server):
    port, paths = test_server
    resp = _opener().open(f"http://127.0.0.1:{port}/api/integrations/github/status")
    data = json.loads(resp.read().decode("utf-8"))
    assert data["configured"] is True
    assert data["connected"] is False
    assert data["redirect_uri"] == f"http://127.0.0.1:{port}/api/integrations/github/callback"


def test_connect_requires_admin(test_server):
    port, paths = test_server
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/integrations/github/connect", method="POST"
    )
    resp = _opener().open(req)
    assert resp.status == 401


def test_connect_returns_authorize_url_with_state(test_server):
    port, paths = test_server
    cookie = _admin_cookie(port, paths)

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/integrations/github/connect", method="POST"
    )
    req.add_header("Cookie", cookie)
    resp = _opener().open(req)
    data = json.loads(resp.read().decode("utf-8"))

    assert data["authorize_url"].startswith("https://github.com/login/oauth/authorize?")
    parsed = urllib.parse.urlparse(data["authorize_url"])
    qs = urllib.parse.parse_qs(parsed.query)
    assert qs["client_id"] == ["test-client-id"]
    assert qs["redirect_uri"] == [f"http://127.0.0.1:{port}/api/integrations/github/callback"]
    assert "state" in qs and len(qs["state"][0]) > 10


def test_full_connect_callback_flow_connects_account(test_server):
    port, paths = test_server
    cookie = _admin_cookie(port, paths)

    # Step 1: admin initiates OAuth, gets an authorize_url containing state.
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/integrations/github/connect", method="POST"
    )
    req.add_header("Cookie", cookie)
    resp = _opener().open(req)
    data = json.loads(resp.read().decode("utf-8"))
    state = urllib.parse.parse_qs(urllib.parse.urlparse(data["authorize_url"]).query)["state"][0]

    # Step 2: simulate GitHub redirecting back with a code + the same state.
    # Only the outbound calls to github.com are mocked; everything else
    # (state validation, session/cookie handling, config persistence) is real.
    with patch(
        "visual_regression.dashboard_server.exchange_code_for_token",
        return_value={"access_token": "gho_fake_token_123", "scope": "read:user", "token_type": "bearer"},
    ) as mock_exchange, patch(
        "visual_regression.dashboard_server.fetch_github_user",
        return_value={
            "login": "kiayen",
            "avatar_url": "https://avatars.githubusercontent.com/u/1",
            "html_url": "https://github.com/kiayen",
        },
    ) as mock_fetch_user:
        callback_url = (
            f"http://127.0.0.1:{port}/api/integrations/github/callback"
            f"?code=fake-code-abc&state={urllib.parse.quote(state)}"
        )
        resp = _opener().open(callback_url)
        assert resp.status == 307
        assert resp.getheader("Location") == "/integrations?github=connected"

        mock_exchange.assert_called_once()
        assert mock_exchange.call_args.kwargs["code"] == "fake-code-abc"
        mock_fetch_user.assert_called_once_with("gho_fake_token_123")

    # Step 3: verify the connection actually persisted.
    status_resp = _opener().open(f"http://127.0.0.1:{port}/api/integrations/github/status")
    status = json.loads(status_resp.read().decode("utf-8"))
    assert status["connected"] is True
    assert status["login"] == "kiayen"
    assert status["profile_url"] == "https://github.com/kiayen"

    # Step 4: the state must be single-use — replaying the callback fails.
    replay_url = (
        f"http://127.0.0.1:{port}/api/integrations/github/callback"
        f"?code=another-code&state={urllib.parse.quote(state)}"
    )
    resp = _opener().open(replay_url)
    assert resp.status == 307
    assert "github_error" in resp.getheader("Location")


def test_callback_rejects_invalid_state(test_server):
    port, paths = test_server
    resp = _opener().open(
        f"http://127.0.0.1:{port}/api/integrations/github/callback?code=x&state=bogus-state"
    )
    assert resp.status == 307
    assert resp.getheader("Location") == "/integrations?github_error=Invalid+or+expired+state"


def test_callback_missing_code_or_state(test_server):
    port, paths = test_server
    resp = _opener().open(f"http://127.0.0.1:{port}/api/integrations/github/callback")
    assert resp.status == 307
    assert "Missing" in resp.getheader("Location")


def test_callback_propagates_github_error_param(test_server):
    port, paths = test_server
    resp = _opener().open(
        f"http://127.0.0.1:{port}/api/integrations/github/callback"
        f"?error=access_denied&error_description=The+user+denied+access"
    )
    assert resp.status == 307
    location = resp.getheader("Location")
    assert location.startswith("/integrations?github_error=")
    assert "denied" in location


def test_callback_handles_token_exchange_error(test_server):
    port, paths = test_server
    cookie = _admin_cookie(port, paths)

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/integrations/github/connect", method="POST"
    )
    req.add_header("Cookie", cookie)
    resp = _opener().open(req)
    data = json.loads(resp.read().decode("utf-8"))
    state = urllib.parse.parse_qs(urllib.parse.urlparse(data["authorize_url"]).query)["state"][0]

    with patch(
        "visual_regression.dashboard_server.exchange_code_for_token",
        return_value={"error": "bad_verification_code", "error_description": "The code passed is incorrect or expired."},
    ):
        callback_url = (
            f"http://127.0.0.1:{port}/api/integrations/github/callback"
            f"?code=stale-code&state={urllib.parse.quote(state)}"
        )
        resp = _opener().open(callback_url)
        assert resp.status == 307
        assert "incorrect" in urllib.parse.unquote(resp.getheader("Location"))

    status_resp = _opener().open(f"http://127.0.0.1:{port}/api/integrations/github/status")
    status = json.loads(status_resp.read().decode("utf-8"))
    assert status["connected"] is False


def test_disconnect_clears_connection(test_server):
    port, paths = test_server
    cookie = _admin_cookie(port, paths)

    from visual_regression.integrations_manager import IntegrationsManager
    manager = IntegrationsManager(paths.root)
    manager.complete_github_oauth(
        access_token="tok",
        user={"login": "someone", "avatar_url": "", "html_url": "https://github.com/someone"},
        scopes=["read:user"],
    )

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/integrations/github/disconnect", method="POST"
    )
    req.add_header("Cookie", cookie)
    resp = _opener().open(req)
    assert resp.status == 200

    status_resp = _opener().open(f"http://127.0.0.1:{port}/api/integrations/github/status")
    status = json.loads(status_resp.read().decode("utf-8"))
    assert status["connected"] is False
