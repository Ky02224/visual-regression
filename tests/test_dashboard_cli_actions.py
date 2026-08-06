"""The dashboard's CLI-action plumbing, including the branch users actually run.

`_run_cli_action_helper` has two halves. Under the test suite it shells out to a
subprocess, which the suite can patch and bound with a timeout. Everywhere else
it calls `cli.main()` in-process, on the request thread. `tests/conftest.py`
sets VRT_TEST_MODE=1 for the whole session at import, so every other test in
this repo takes the subprocess half — the in-process half, the one every real
deployment runs, had no coverage at all.

That gap is why a 20-epoch training run could sit on the request thread
unnoticed: in tests it was a bounded child process, and it looked fine.
"""
import os

import pytest

import visual_regression.dashboard_server as server
from visual_regression.config import WorkspacePaths


@pytest.fixture
def production_mode(monkeypatch):
    """Undo conftest's VRT_TEST_MODE for the duration of one test."""
    monkeypatch.delenv("VRT_TEST_MODE", raising=False)
    assert not server._is_test_environment(), (
        "with VRT_TEST_MODE unset and subprocess.run unmocked, the helper must "
        "take the in-process branch — otherwise this file tests nothing"
    )
    yield


@pytest.fixture
def paths(tmp_path):
    p = WorkspacePaths(root=tmp_path / ".visual-regression")
    p.ensure()
    return p


class TestInProcessBranch:
    def test_runs_the_cli_in_process_and_captures_its_output(
        self, production_mode, paths, tmp_path, monkeypatch
    ):
        seen = {}

        def fake_main(argv):
            seen["argv"] = list(argv)
            print("captured stdout line")
            return 0

        monkeypatch.setattr("visual_regression.cli.main", fake_main)
        # dashboard_server installs `sys.stdout = _stdout_proxy` at import, and
        # that is what routes an action's output into a per-thread buffer.
        # pytest re-installs its own capture at the start of each test phase,
        # which undoes the module's assignment — so this has to be restored
        # here, in the call phase, rather than in a fixture that setup would
        # apply and the phase change would then overwrite.
        monkeypatch.setattr("sys.stdout", server._stdout_proxy)

        result = server._run_cli_action_helper(paths, tmp_path, 8100, ["list-baselines"])

        assert result["returncode"] == 0
        assert "captured stdout line" in result["stdout"]
        # The workspace has to be forwarded, or the action runs against whatever
        # root the server process happens to have.
        assert "--root" in seen["argv"]
        assert str(paths.root) in seen["argv"]

    def test_an_exception_becomes_a_failed_result_not_a_500(
        self, production_mode, paths, tmp_path, monkeypatch
    ):
        """A crashing action must not take the request handler down with it."""
        def boom(argv):
            raise RuntimeError("action exploded")

        monkeypatch.setattr("visual_regression.cli.main", boom)

        result = server._run_cli_action_helper(paths, tmp_path, 8100, ["compare"])

        assert result["returncode"] == 1
        assert "action exploded" in result["stderr"]

    def test_an_explicit_root_is_not_overridden(
        self, production_mode, paths, tmp_path, monkeypatch
    ):
        seen = {}
        monkeypatch.setattr(
            "visual_regression.cli.main",
            lambda argv: (seen.update(argv=list(argv)), 0)[1],
        )

        server._run_cli_action_helper(
            paths, tmp_path, 8100, ["list-runs", "--root", "/explicit/root"])

        assert seen["argv"].count("--root") == 1
        assert "/explicit/root" in seen["argv"]


class TestLongActionsDoNotBlockTheRequest:
    """Training and full-suite capture take minutes to hours.

    Held on the request thread they exhaust the worker pool, give the caller
    nothing but a timeout, and leave the run with no id to cancel or watch.
    Both must hand back a task id instead.
    """

    @staticmethod
    def _client():
        from fastapi.testclient import TestClient
        return TestClient(server.app, raise_server_exceptions=False)

    @pytest.mark.parametrize("route", [
        "/api/actions/train-ai",
        "/api/actions/create-demo-baselines",
    ])
    def test_returns_a_task_id_rather_than_running_to_completion(
        self, route, tmp_path, monkeypatch
    ):
        captured = {}

        def fake_async(paths, project_root, port, args, use_subprocess=False):
            captured["args"] = list(args)
            return "task-abc"

        def fake_sync(*a, **k):
            raise AssertionError(
                f"{route} ran the CLI synchronously — the caller's request is "
                "held open for the whole job"
            )

        monkeypatch.setattr(server, "_run_cli_action_async_helper", fake_async)
        monkeypatch.setattr(server, "_run_cli_action_helper", fake_sync)

        paths = WorkspacePaths(root=tmp_path / ".visual-regression")
        paths.ensure()
        monkeypatch.setattr(server.app.state, "paths", paths, raising=False)
        monkeypatch.setattr(server.app.state, "project_root", tmp_path, raising=False)

        from visual_regression.sqlite_store import SqliteStore
        store = SqliteStore(paths.root / "storage.db")
        store.create_user("dev@example.com", "pw", "admin", "Dev")
        monkeypatch.setattr(server.app.state, "store", store, raising=False)

        client = self._client()
        client.cookies.set("lens_session", store.create_session("dev@example.com"))
        response = client.post(route, json={})

        assert response.status_code == 200, response.text
        assert response.json().get("task_id") == "task-abc"
        assert captured["args"], "the action never reached the background runner"


class TestIncompleteRequestsAreRejectedBeforeTheCLIRuns:
    """A missing name is the caller's mistake.

    Forwarded to the CLI it came back as a failed subprocess reported as 500,
    which tells the client the server broke when the request was simply
    incomplete, and buries the reason in captured stderr. It also pays for a
    process launch to discover something checkable up front.
    """

    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient
        from visual_regression.sqlite_store import SqliteStore

        paths = WorkspacePaths(root=tmp_path / ".visual-regression")
        paths.ensure()
        store = SqliteStore(paths.root / "storage.db")
        store.create_user("admin@example.com", "pw", "admin", "Admin")
        monkeypatch.setattr(server.app.state, "paths", paths, raising=False)
        monkeypatch.setattr(server.app.state, "store", store, raising=False)
        monkeypatch.setattr(server.app.state, "project_root", tmp_path, raising=False)

        def never(*a, **k):
            raise AssertionError("the CLI was invoked for a request that could not succeed")

        monkeypatch.setattr(server, "_run_cli_action_helper", never)
        monkeypatch.setattr(server, "_run_cli_action_async_helper", never)

        c = TestClient(server.app, raise_server_exceptions=False)
        c.cookies.set("lens_session", store.create_session("admin@example.com"))
        return c

    @pytest.mark.parametrize("payload", [{}, {"name": ""}, {"name": "   "}])
    def test_create_baseline_without_a_name_is_400(self, client, payload):
        response = client.post("/api/actions/create-baseline", json=payload)

        assert response.status_code == 400, f"{payload} -> {response.status_code}"

    @pytest.mark.parametrize("name", ["", "   "])
    def test_the_matrix_branch_of_compare_also_checks_the_name(self, client, name):
        """More than one browser/device/locale routes /api/actions/compare into
        compare-matrix, which built its args straight from the payload. The
        single-comparison branch beside it already answers 404/400 for the same
        omission."""
        response = client.post(
            "/api/actions/compare",
            json={"name": name, "browsers": ["chromium", "firefox"]},
        )

        assert response.status_code == 400, f"name={name!r} -> {response.status_code}"
