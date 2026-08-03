"""Endpoint-level tests for the standalone inference microservice.

test_model_server_inference.py covers _run_single_infer and the API-key gate.
This file covers the HTTP surface around them, driven through FastAPI's
TestClient so the dependency wiring is exercised rather than bypassed.

The security-relevant case is /model/reload: it hands an arbitrary local path to
torch.load(weights_only=False), which executes objects embedded in the
checkpoint — a pickle-deserialization RCE primitive. Its gate must fail closed
when no key is configured, which is the state a fresh deployment starts in.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import visual_regression.model_server as model_server
from visual_regression.model_server import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """Reset the module globals so tests cannot leak a loaded model into each other."""
    monkeypatch.setattr(model_server, "_LOADED_MODEL", None)
    monkeypatch.setattr(model_server, "_MODEL_PATH", None)
    monkeypatch.delenv("VRT_MODEL_SERVER_API_KEY", raising=False)


@pytest.fixture
def loaded_model(monkeypatch):
    fake = {
        "type": "hybrid-multiclass",
        "image_size": 224,
        "threshold": 0.35,
        "class_names": ["insignificant-change", "layout-issue"],
    }
    monkeypatch.setattr(model_server, "_LOADED_MODEL", fake)
    monkeypatch.setattr(model_server, "_MODEL_PATH", "/models/visual_ai.pt")
    return fake


# ---------------------------------------------------------------------------
# Unauthenticated endpoints
# ---------------------------------------------------------------------------

class TestHealth:
    def test_reports_healthy_without_a_model(self, client):
        """The container healthcheck must pass before a model is loaded, or the
        orchestrator kills the service during startup."""
        body = client.get("/health").json()
        assert body["status"] == "healthy"
        assert body["model_loaded"] is False
        assert body["model_path"] is None

    def test_reports_the_loaded_model(self, client, loaded_model):
        body = client.get("/health").json()
        assert body["model_loaded"] is True
        assert body["model_path"] == "/models/visual_ai.pt"

    def test_needs_no_api_key(self, client, monkeypatch):
        monkeypatch.setenv("VRT_MODEL_SERVER_API_KEY", "secret")
        assert client.get("/health").status_code == 200


class TestModelInfo:
    def test_404s_when_no_model_is_loaded(self, client):
        assert client.get("/model/info").status_code == 404

    def test_returns_the_model_metadata(self, client, loaded_model):
        body = client.get("/model/info").json()
        assert body["type"] == "hybrid-multiclass"
        assert body["image_size"] == 224
        assert body["class_names"] == ["insignificant-change", "layout-issue"]

    def test_exposes_class_names_so_callers_can_map_indices(self, client, loaded_model):
        """A caller that assumed its own ordering would mislabel every
        prediction; the server has to publish the ordering it was trained with."""
        assert client.get("/model/info").json()["class_names"] is not None


class TestMetrics:
    def test_reports_zero_when_no_model_is_loaded(self, client):
        assert client.get("/metrics").json()["model_loaded"] == 0

    def test_reports_one_when_a_model_is_loaded(self, client, loaded_model):
        assert client.get("/metrics").json()["model_loaded"] == 1


# ---------------------------------------------------------------------------
# The gated endpoint
# ---------------------------------------------------------------------------

class TestReloadAuthorisation:
    def test_fails_closed_when_no_key_is_configured(self, client):
        """A fresh deployment has no key set. If that left the route open,
        anyone reachable could point it at a malicious checkpoint and get code
        execution via torch.load."""
        assert client.post("/model/reload", params={"path": "/tmp/x.pt"}).status_code == 403

    def test_rejects_a_missing_header(self, client, monkeypatch):
        monkeypatch.setenv("VRT_MODEL_SERVER_API_KEY", "secret")
        assert client.post("/model/reload", params={"path": "/tmp/x.pt"}).status_code == 403

    def test_rejects_a_wrong_key(self, client, monkeypatch):
        monkeypatch.setenv("VRT_MODEL_SERVER_API_KEY", "secret")
        resp = client.post("/model/reload", params={"path": "/tmp/x.pt"},
                           headers={"X-Access-Key": "wrong"})
        assert resp.status_code == 403

    def test_a_correct_key_reaches_the_handler(self, client, monkeypatch):
        monkeypatch.setenv("VRT_MODEL_SERVER_API_KEY", "secret")
        loaded = {}
        monkeypatch.setattr(model_server, "load_model", lambda path: loaded.update(path=path))

        resp = client.post("/model/reload", params={"path": "/models/new.pt"},
                           headers={"X-Access-Key": "secret"})

        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert str(loaded["path"]) == str(model_server.Path("/models/new.pt"))

    def test_a_failed_load_is_a_400_not_a_500(self, client, monkeypatch):
        monkeypatch.setenv("VRT_MODEL_SERVER_API_KEY", "secret")

        def boom(path):
            raise RuntimeError("not a checkpoint")

        monkeypatch.setattr(model_server, "load_model", boom)

        resp = client.post("/model/reload", params={"path": "/models/bad.pt"},
                           headers={"X-Access-Key": "secret"})

        assert resp.status_code == 400
        assert "not a checkpoint" in resp.json()["detail"]


class TestInferAuthorisation:
    def test_infer_is_gated(self, client):
        resp = client.post("/infer", json={"mismatch_pct": 1.0, "ssim_score": 0.9, "regions": []})
        assert resp.status_code == 403

    def test_batch_infer_is_gated(self, client):
        resp = client.post("/infer/batch", json={"items": []})
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# load_model
# ---------------------------------------------------------------------------

class TestLoadModel:
    def test_wraps_a_load_failure_in_a_runtime_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "visual_regression.ai_training._load_legacy_or_hybrid_model",
            lambda p: (_ for _ in ()).throw(ValueError("corrupt checkpoint")),
        )
        with pytest.raises(RuntimeError, match="Failed to load model"):
            model_server.load_model(tmp_path / "missing.pt")

    def test_records_the_path_on_success(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "visual_regression.ai_training._load_legacy_or_hybrid_model",
            lambda p: {"type": "hybrid-multiclass"},
        )
        target = tmp_path / "visual_ai.pt"

        model_server.load_model(target)

        assert model_server._MODEL_PATH == target
        assert model_server._LOADED_MODEL["type"] == "hybrid-multiclass"


class TestSemaphore:
    def test_is_created_once_and_reused(self):
        """A fresh semaphore per request would defeat the concurrency limit that
        exists to stop CPU/GPU thrashing."""
        first = model_server.get_semaphore()
        assert model_server.get_semaphore() is first
