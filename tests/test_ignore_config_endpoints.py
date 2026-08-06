"""Saving exclusions must not lose them, and must not pretend to save them.

Both endpoints here decide what a comparison is allowed to ignore, so a silent
failure does not look like a failure — it looks like a real defect reported in
an area the reviewer had excluded, or an exclusion that never took effect.

Two distinct faults, found by driving the running dashboard:

  * ignore-regions defaulted a missing key to [], so a request that merely
    omitted the field wiped every region and answered 200 ok. "Absent" and
    "empty" are different instructions and were collapsed into the destructive
    one.
  * ignore-css-selectors returned {"ok": True, "ignore_css_selectors": []}
    unconditionally and stored nothing, with a working
    BaselineManager.save_ignore_css_selectors sitting directly beneath it.
"""
import json

import pytest

import visual_regression.dashboard_server as server
from visual_regression.config import WorkspacePaths
from visual_regression.sqlite_store import SqliteStore

REGION = {"x": 10, "y": 20, "width": 100, "height": 60}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    paths.ensure()
    store = SqliteStore(paths.root / "storage.db")
    store.create_user("admin@example.com", "pw", "admin", "Admin")

    baseline = paths.baselines_dir / "home"
    baseline.mkdir(parents=True, exist_ok=True)
    (baseline / "metadata.json").write_text(json.dumps({"name": "home"}), encoding="utf-8")

    monkeypatch.setattr(server.app.state, "paths", paths, raising=False)
    monkeypatch.setattr(server.app.state, "store", store, raising=False)
    monkeypatch.setattr(server.app.state, "project_root", tmp_path, raising=False)

    c = TestClient(server.app, raise_server_exceptions=False)
    c.cookies.set("lens_session", store.create_session("admin@example.com"))
    c.paths = paths
    return c


def stored(client, key):
    meta = json.loads((client.paths.baselines_dir / "home" / "metadata.json").read_text(encoding="utf-8"))
    return meta.get(key, [])


class TestIgnoreRegions:
    def test_a_region_is_saved(self, client):
        response = client.post("/api/ignore-regions",
                               json={"name": "home", "ignore_regions": [REGION]})

        assert response.status_code == 200, response.text
        assert stored(client, "ignore_regions") == [REGION]

    def test_omitting_the_field_does_not_wipe_what_was_saved(self, client):
        """The regression: this answered 200 and cleared every region."""
        client.post("/api/ignore-regions", json={"name": "home", "ignore_regions": [REGION]})

        response = client.post("/api/ignore-regions", json={"name": "home"})

        assert response.status_code == 400, (
            f"a request with no ignore_regions was accepted ({response.status_code}); "
            "it used to clear them all and report success"
        )
        assert stored(client, "ignore_regions") == [REGION], "the saved region was destroyed"

    def test_an_explicit_empty_list_still_clears(self, client):
        """Clearing must stay possible — the UI clears by sending []."""
        client.post("/api/ignore-regions", json={"name": "home", "ignore_regions": [REGION]})

        response = client.post("/api/ignore-regions", json={"name": "home", "ignore_regions": []})

        assert response.status_code == 200, response.text
        assert stored(client, "ignore_regions") == []


class TestIgnoreCssSelectors:
    def test_selectors_are_actually_persisted(self, client):
        """This endpoint acknowledged and discarded everything sent to it."""
        response = client.post("/api/ignore-css-selectors",
                               json={"name": "home", "ignore_css_selectors": [".ticker", "#clock"]})

        assert response.status_code == 200, response.text
        assert response.json()["ignore_css_selectors"] == [".ticker", "#clock"]
        assert stored(client, "ignore_css_selectors") == [".ticker", "#clock"]

    def test_omitting_the_field_does_not_wipe_them(self, client):
        client.post("/api/ignore-css-selectors",
                    json={"name": "home", "ignore_css_selectors": [".ticker"]})

        response = client.post("/api/ignore-css-selectors", json={"name": "home"})

        assert response.status_code == 400
        assert stored(client, "ignore_css_selectors") == [".ticker"]

    def test_an_explicit_empty_list_clears(self, client):
        client.post("/api/ignore-css-selectors",
                    json={"name": "home", "ignore_css_selectors": [".ticker"]})

        response = client.post("/api/ignore-css-selectors",
                               json={"name": "home", "ignore_css_selectors": []})

        assert response.status_code == 200
        assert stored(client, "ignore_css_selectors") == []

    def test_an_unknown_baseline_is_404_not_a_silent_success(self, client):
        response = client.post("/api/ignore-css-selectors",
                               json={"name": "no-such-baseline", "ignore_css_selectors": [".x"]})

        assert response.status_code == 404

    def test_a_non_list_is_rejected(self, client):
        response = client.post("/api/ignore-css-selectors",
                               json={"name": "home", "ignore_css_selectors": ".ticker"})

        assert response.status_code == 400
