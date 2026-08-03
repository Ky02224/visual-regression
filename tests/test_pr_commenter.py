"""Tests for the PR comment generator and its GitHub calls.

This module posts to the GitHub API and writes the comment CI publishes, and it
had no tests. Everything here runs offline: `post_to_github` is exercised with
urlopen patched out, so no network request is ever made.
"""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from visual_regression.config import WorkspacePaths
from visual_regression.pr_commenter import _is_permanent_error, main, post_to_github


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_run(paths: WorkspacePaths, name: str, payload: dict) -> None:
    run_dir = paths.runs_dir / name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "result.json").write_text(json.dumps(payload), encoding="utf-8")


def _fail_run(case_name: str, mismatch: float = 12.5, build_id: str = "build_1") -> dict:
    return {
        "case_name": case_name,
        "build_id": build_id,
        "status": "FAIL",
        "threshold_pct": 0.5,
        "capture": {"browser": "chromium", "viewport": [1440, 900]},
        "result": {"mismatch_pct": mismatch},
        "ai_assessment": {"label": "layout-issue"},
        "severity": {"level": "high"},
    }


def _pass_run(case_name: str, build_id: str = "build_1") -> dict:
    return {
        "case_name": case_name,
        "build_id": build_id,
        "status": "PASS",
        "threshold_pct": 0.5,
        "capture": {"browser": "chromium", "viewport": [1440, 900]},
        "result": {"mismatch_pct": 0.0},
    }


@pytest.fixture
def workspace(tmp_path):
    paths = WorkspacePaths(tmp_path / ".visual-regression")
    paths.ensure()
    return paths


@pytest.fixture(autouse=True)
def _no_github_env(monkeypatch):
    """Keep every test offline even if the developer's shell has these set."""
    for var in ("GITHUB_TOKEN", "GITHUB_REPOSITORY", "GITHUB_SHA",
                "GITHUB_EVENT_PATH", "GITHUB_REF", "VISUAL_DASHBOARD_URL"):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Retry classification
# ---------------------------------------------------------------------------

class TestPermanentErrorClassification:
    @pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
    def test_client_errors_are_permanent(self, code):
        """A bad token or wrong repo will never succeed on retry — burning the
        full backoff budget on it just slows the build down."""
        exc = urllib.error.HTTPError("u", code, "msg", {}, None)
        assert _is_permanent_error(exc) is True

    @pytest.mark.parametrize("code", [500, 502, 503, 504, 429])
    def test_server_errors_and_rate_limits_are_retriable(self, code):
        exc = urllib.error.HTTPError("u", code, "msg", {}, None)
        assert _is_permanent_error(exc) is False

    def test_non_http_errors_are_retriable(self):
        assert _is_permanent_error(urllib.error.URLError("connection refused")) is False
        assert _is_permanent_error(TimeoutError("timed out")) is False


# ---------------------------------------------------------------------------
# Markdown generation
# ---------------------------------------------------------------------------

class TestMarkdownGeneration:
    def test_writes_a_pass_comment_when_nothing_failed(self, workspace):
        _write_run(workspace, "20260101-000001_a", _pass_run("home"))
        _write_run(workspace, "20260101-000002_b", _pass_run("login"))

        main(paths=workspace)

        body = (workspace.root / "pr_comment.md").read_text(encoding="utf-8")
        assert "Visual Regression Passed" in body
        assert "**2**" in body

    def test_failure_comment_lists_each_failing_case(self, workspace):
        _write_run(workspace, "20260101-000001_a", _pass_run("home"))
        _write_run(workspace, "20260101-000002_b", _fail_run("login", mismatch=12.5))

        main(paths=workspace)

        body = (workspace.root / "pr_comment.md").read_text(encoding="utf-8")
        assert "Visual Regression Detected" in body
        assert "`login`" in body
        assert "12.50%" in body
        assert "HIGH" in body
        assert "`layout-issue`" in body

    def test_only_the_latest_build_is_reported(self, workspace):
        """Runs accumulate across builds; a comment mixing them would report
        failures the current commit did not cause."""
        _write_run(workspace, "20260101-000001_old", _fail_run("stale", build_id="build_0"))
        _write_run(workspace, "20260101-000002_new", _pass_run("fresh", build_id="build_1"))

        main(paths=workspace)

        body = (workspace.root / "pr_comment.md").read_text(encoding="utf-8")
        assert "Visual Regression Passed" in body
        assert "stale" not in body

    def test_unreadable_result_json_is_skipped_not_fatal(self, workspace, capsys):
        _write_run(workspace, "20260101-000002_ok", _pass_run("home"))
        bad = workspace.runs_dir / "20260101-000001_bad"
        bad.mkdir(parents=True)
        (bad / "result.json").write_text("{not json", encoding="utf-8")

        main(paths=workspace)

        assert "[WARN]" in capsys.readouterr().out
        assert (workspace.root / "pr_comment.md").exists()

    def test_no_runs_writes_no_comment(self, workspace, capsys):
        main(paths=workspace)
        assert "No test results found." in capsys.readouterr().out
        assert not (workspace.root / "pr_comment.md").exists()

    def test_missing_runs_directory_is_handled(self, tmp_path, capsys):
        paths = WorkspacePaths(tmp_path / "absent")
        main(paths=paths)
        assert "Runs directory not found." in capsys.readouterr().out

    def test_device_name_is_preferred_over_viewport_width(self, workspace):
        run = _fail_run("mobile")
        run["capture"]["device"] = "iPhone 13"
        _write_run(workspace, "20260101-000001_a", run)

        main(paths=workspace)

        assert "iPhone 13" in (workspace.root / "pr_comment.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# GitHub API interaction (never hits the network)
# ---------------------------------------------------------------------------

class _FakeResponse:
    status = 201

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestPostToGitHub:
    def test_skips_entirely_without_a_token(self, monkeypatch, capsys):
        called = []
        monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: called.append(1))

        post_to_github("body", False, 0, 3)

        assert called == []
        assert "GitHub integration skipped" in capsys.readouterr().out

    def test_posts_a_failure_commit_status(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("GITHUB_SHA", "abc123")
        sent = []

        def fake_urlopen(req, timeout=None):
            sent.append((req.full_url, json.loads(req.data.decode())))
            return _FakeResponse()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

        post_to_github("body", True, 2, 5)

        url, payload = sent[0]
        assert url == "https://api.github.com/repos/owner/repo/statuses/abc123"
        assert payload["state"] == "failure"
        assert payload["context"] == "visual-regression/mismatch-check"
        assert "2 failures" in payload["description"]

    def test_success_state_when_nothing_failed(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("GITHUB_SHA", "abc123")
        sent = []
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda req, timeout=None: (sent.append(json.loads(req.data.decode())), _FakeResponse())[1],
        )

        post_to_github("body", False, 0, 5)

        assert sent[0]["state"] == "success"

    def test_pr_number_is_read_from_the_event_payload(self, monkeypatch, tmp_path):
        event = tmp_path / "event.json"
        event.write_text(json.dumps({"pull_request": {"number": 42}}), encoding="utf-8")
        monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
        urls = []
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda req, timeout=None: (urls.append(req.full_url), _FakeResponse())[1],
        )

        post_to_github("hello", False, 0, 1)

        assert "https://api.github.com/repos/owner/repo/issues/42/comments" in urls

    def test_pr_number_falls_back_to_github_ref(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("GITHUB_REF", "refs/pull/77/merge")
        urls = []
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda req, timeout=None: (urls.append(req.full_url), _FakeResponse())[1],
        )

        post_to_github("hello", False, 0, 1)

        assert "https://api.github.com/repos/owner/repo/issues/77/comments" in urls

    def test_a_permanent_error_is_not_retried(self, monkeypatch):
        """403 means the token lacks permission; three attempts with backoff
        would add ~6s to every CI run and still fail."""
        monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("GITHUB_SHA", "abc123")
        attempts = []

        def always_403(req, timeout=None):
            attempts.append(1)
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", always_403)
        monkeypatch.setattr("time.sleep", lambda s: None)

        post_to_github("body", True, 1, 1)

        assert len(attempts) == 1

    def test_a_transient_error_is_retried_to_the_limit(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("GITHUB_SHA", "abc123")
        attempts = []

        def always_503(req, timeout=None):
            attempts.append(1)
            raise urllib.error.HTTPError(req.full_url, 503, "Unavailable", {}, None)

        monkeypatch.setattr("urllib.request.urlopen", always_503)
        monkeypatch.setattr("time.sleep", lambda s: None)

        post_to_github("body", True, 1, 1)

        assert len(attempts) == 3

    def test_dashboard_url_is_attached_when_configured(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("GITHUB_SHA", "abc123")
        monkeypatch.setenv("VISUAL_DASHBOARD_URL", "https://lens.example.com/run/1")
        sent = []
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda req, timeout=None: (sent.append(json.loads(req.data.decode())), _FakeResponse())[1],
        )

        post_to_github("body", False, 0, 1)

        assert sent[0]["target_url"] == "https://lens.example.com/run/1"

    def test_the_auth_token_is_sent_as_a_header_not_in_the_url(self, monkeypatch):
        """A token in the query string ends up in server logs and referrers."""
        monkeypatch.setenv("GITHUB_TOKEN", "s3cret")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("GITHUB_SHA", "abc123")
        captured = []
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda req, timeout=None: (captured.append(req), _FakeResponse())[1],
        )

        post_to_github("body", False, 0, 1)

        req = captured[0]
        assert "s3cret" not in req.full_url
        assert req.headers["Authorization"] == "token s3cret"
