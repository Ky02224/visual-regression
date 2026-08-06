"""A served image's Content-Type must describe its bytes, not its filename.

reporter.save_image encodes WebP and writes it to whatever path it is given, so
a stored file's extension says nothing about its encoding. Both directions occur
in this workspace: 108 baselines hold WebP bytes under a `baseline.png` name,
and save_image documents the reverse — a screenshot taller than WebP's 16383px
limit falls back to PNG bytes under whatever name was requested.

FileResponse takes Content-Type from the extension, so it announced the wrong
type in both cases. Browsers sniff the payload and render it regardless, which
is exactly why this went unnoticed: nothing looked broken. It still matters,
because Content-Type is the only thing a non-browser consumer has to go on.
"""
import cv2
import numpy as np
import pytest

import visual_regression.dashboard_server as server
from visual_regression.config import WorkspacePaths
from visual_regression.sqlite_store import SqliteStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    paths.ensure()
    store = SqliteStore(paths.root / "storage.db")
    store.create_user("admin@example.com", "pw", "admin", "Admin")

    monkeypatch.setattr(server.app.state, "paths", paths, raising=False)
    monkeypatch.setattr(server.app.state, "store", store, raising=False)
    monkeypatch.setattr(server.app.state, "project_root", tmp_path, raising=False)

    c = TestClient(server.app, raise_server_exceptions=False)
    c.cookies.set("lens_session", store.create_session("admin@example.com"))
    c.paths = paths
    return c


def _write(path, ext):
    """Encode a small image as `ext` and store it at `path`, whatever `path` is named."""
    path.parent.mkdir(parents=True, exist_ok=True)
    image = np.full((8, 8, 3), 127, dtype=np.uint8)
    ok, buf = cv2.imencode(ext, image)
    assert ok, f"could not encode {ext}"
    path.write_bytes(buf.tobytes())


class TestBaselineImages:
    def test_webp_bytes_under_a_png_name_are_served_as_webp(self, client):
        """The shape 108 baselines in this workspace are actually in."""
        _write(client.paths.baselines_dir / "case" / "baseline.png", ".webp")

        response = client.get("/baseline/case/baseline.png")

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/webp"

    def test_png_bytes_under_a_webp_name_are_served_as_png(self, client):
        """The reverse, which save_image produces for pages taller than 16383px."""
        _write(client.paths.baselines_dir / "tall" / "baseline.webp", ".png")

        response = client.get("/baseline/tall/baseline.webp")

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"

    def test_the_legacy_png_fallback_still_reports_the_real_type(self, client):
        """The frontend requests .webp; _resolve_with_legacy_png finds the .png
        beside it. The type must follow the file that was actually served."""
        _write(client.paths.baselines_dir / "legacy" / "baseline.png", ".webp")

        response = client.get("/baseline/legacy/baseline.webp")

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/webp"


class TestRunArtifacts:
    def test_an_artifact_reports_the_type_of_its_bytes(self, client):
        _write(client.paths.runs_dir / "run-1" / "diff_overlay.png", ".webp")

        response = client.get("/artifacts/run-1/diff_overlay.png")

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/webp"


class TestNonImagesAreUntouched:
    def test_a_json_artifact_keeps_its_own_type(self, client):
        path = client.paths.runs_dir / "run-2" / "result.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"ok": true}', encoding="utf-8")

        response = client.get("/artifacts/run-2/result.json")

        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]

    def test_an_unrecognisable_image_falls_back_to_the_extension(self, client):
        """Sniffing must not turn an unreadable file into a hard failure; the
        extension is still the best guess available."""
        path = client.paths.runs_dir / "run-3" / "current.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not an image at all")

        response = client.get("/artifacts/run-3/current.png")

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
