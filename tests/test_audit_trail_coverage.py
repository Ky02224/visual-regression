"""What the audit trail is required to record.

The trail covered authentication and user management, and the approve/reject
decision — but not the operations that destroy evidence or hand out the
credential. The gap showed up as an inconsistency rather than an absence: who
approved a run was recorded, who deleted it was not, so the trail could hold a
decision about a run that no longer existed and name nobody for its removal.

These pin the operations that must leave a record, and assert the secret is not
copied into the record while doing so.
"""
import pytest

import visual_regression.dashboard_server as server
from visual_regression.config import WorkspacePaths
from visual_regression.integrations_manager import IntegrationsManager
from visual_regression.sqlite_store import SqliteStore


@pytest.fixture
def env(tmp_path, monkeypatch):
    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    paths.ensure()
    store = SqliteStore(paths.root / "storage.db")
    store.create_user("admin@example.com", "pw", "admin", "Admin")
    token = store.create_session("admin@example.com")

    monkeypatch.setattr(server.app.state, "paths", paths, raising=False)
    monkeypatch.setattr(server.app.state, "store", store, raising=False)
    monkeypatch.setattr(server.app.state, "project_root", tmp_path, raising=False)

    from fastapi.testclient import TestClient
    client = TestClient(server.app, raise_server_exceptions=False)
    client.cookies.set("lens_session", token)
    return {"client": client, "store": store, "paths": paths}


def actions(store):
    return [row["action"] for row in store.get_audit_logs(limit=200)]


def entry(store, action):
    for row in store.get_audit_logs(limit=200):
        if row["action"] == action:
            return row
    raise AssertionError(f"no audit entry for {action!r}; got {actions(store)}")


class TestDestructiveOperationsAreRecorded:
    def test_deleting_a_run_is_audited(self, env, monkeypatch):
        monkeypatch.setattr(
            "visual_regression.review_manager.ReviewManager.delete_run",
            lambda self, ref: {"deleted": ref},
        )

        response = env["client"].post("/api/run/delete", json={"run": "20260806-run-x"})

        assert response.status_code == 200, response.text
        row = entry(env["store"], "run.delete")
        assert row["actor_email"] == "admin@example.com"
        assert row["detail"]["run"] == "20260806-run-x"

    def test_a_rejected_delete_is_not_recorded_as_one(self, env):
        """An entry for a request that never deleted anything would claim a run
        was destroyed when it still exists."""
        response = env["client"].post("/api/run/delete", json={"run": ""})

        assert response.status_code == 400
        assert "run.delete" not in actions(env["store"])

    def test_restoring_a_baseline_version_is_audited(self, env, monkeypatch):
        monkeypatch.setattr(
            "visual_regression.baseline_manager.BaselineManager.restore_version",
            lambda self, name, version, restored_by=None: {"restored": version},
        )

        response = env["client"].post(
            "/api/baseline/restore", json={"name": "home", "version": "v3"})

        assert response.status_code == 200, response.text
        row = entry(env["store"], "baseline.restore")
        assert row["detail"]["version"] == "v3"


class TestCredentialAccessIsRecorded:
    def test_revealing_the_api_key_is_audited(self, env):
        response = env["client"].post("/api/integrations/reveal-key")

        assert response.status_code == 200, response.text
        entry(env["store"], "integrations.reveal_key")

    def test_the_revealed_key_is_not_copied_into_the_audit_detail(self, env):
        """The trail is readable by any admin. Recording the secret there turns
        the log into a second place it lives."""
        revealed = env["client"].post("/api/integrations/reveal-key").json()["api_key"]

        assert revealed, "nothing to check if no key was issued"
        row = entry(env["store"], "integrations.reveal_key")
        assert revealed not in str(row["detail"])

    def test_rotating_the_api_key_is_audited(self, env):
        response = env["client"].post("/api/integrations/rotate-key")

        assert response.status_code == 200, response.text
        row = entry(env["store"], "integrations.rotate_key")
        assert response.json()["api_key"] not in str(row["detail"])

    def test_rotation_invalidates_the_previous_key(self, env):
        """Auditing the rotation is worth nothing if the old key still works."""
        manager = IntegrationsManager(env["paths"].root)
        before = manager.reveal_api_key()

        after = env["client"].post("/api/integrations/rotate-key").json()["api_key"]

        assert after != before
        assert IntegrationsManager(env["paths"].root).reveal_api_key() == after


class TestTheseRoutesRejectNonAdmins:
    """All four are admin-only. A viewer session must not reach any of them."""

    @pytest.fixture
    def viewer_client(self, env):
        env["store"].create_user("viewer@example.com", "pw", "viewer", "Viewer")
        from fastapi.testclient import TestClient
        client = TestClient(server.app, raise_server_exceptions=False)
        client.cookies.set("lens_session", env["store"].create_session("viewer@example.com"))
        return client

    @pytest.mark.parametrize("route,body", [
        ("/api/run/delete", {"run": "x"}),
        ("/api/baseline/restore", {"name": "home", "version": "v1"}),
        ("/api/integrations/reveal-key", None),
        ("/api/integrations/rotate-key", None),
    ])
    def test_viewer_is_forbidden(self, viewer_client, env, route, body):
        response = viewer_client.post(route, json=body if body is not None else {})

        assert response.status_code == 403, f"{route} -> {response.status_code}"
        assert not actions(env["store"]) or "run.delete" not in actions(env["store"])
