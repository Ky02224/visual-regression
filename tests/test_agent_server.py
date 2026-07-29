"""Regression tests for the distributed capture agent's authentication.

The agent's /capture endpoint drives a real headless browser to whatever
URL a caller supplies and streams the rendered page back — without a
shared-secret check, any host that can reach this port could use it as an
unauthenticated SSRF proxy. See cli.py's AgentHTTPHandler.do_POST.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from visual_regression.cli import AgentHTTPHandler


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def agent_server(monkeypatch):
    monkeypatch.setenv("VRT_AGENT_TOKEN", "test-shared-secret")
    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), AgentHTTPHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield port
    server.shutdown()
    server.server_close()
    t.join(timeout=2)


def _post_capture(port: int, body: dict, token: str | None) -> tuple[int, bytes]:
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-Agent-Token"] = token
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/capture",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_capture_rejects_missing_token(agent_server):
    status, body = _post_capture(agent_server, {"name": "x", "url": "http://example.com"}, token=None)
    assert status == 401
    assert b"X-Agent-Token" in body


def test_capture_rejects_wrong_token(agent_server):
    status, body = _post_capture(agent_server, {"name": "x", "url": "http://example.com"}, token="wrong-secret")
    assert status == 401


def test_capture_rejects_non_http_scheme_even_with_valid_token(agent_server):
    # file:// (or any non-http(s) scheme) reaching a real browser navigation
    # would let an authenticated-but-malicious caller read local files off
    # the agent host instead of just SSRF-ing other network services.
    status, body = _post_capture(
        agent_server, {"name": "x", "url": "file:///etc/passwd"}, token="test-shared-secret",
    )
    assert status == 500
    data = json.loads(body)
    assert "scheme" in data.get("error", "")


def test_agent_refuses_to_start_without_token(monkeypatch, capsys):
    from visual_regression.cli import cmd_agent
    monkeypatch.delenv("VRT_AGENT_TOKEN", raising=False)
    rc = cmd_agent(type("Args", (), {"host": "127.0.0.1", "port": _free_port()})())
    assert rc == 1
    assert "VRT_AGENT_TOKEN" in capsys.readouterr().out
