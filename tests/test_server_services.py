"""Tests for the two service handlers behind the dashboard's write endpoints.

The original test here is the regression for handle_ignore_regions_update, which
used to crash with `UnboundLocalError: cannot access local variable
'BaselineManager' where it is not associated with a value` on every call: a
redundant `from .baseline_manager import BaselineManager` deep inside the
function's `if run_id:` branch made Python treat the name as local for the
*entire* function, shadowing the module-level import used earlier in the
same function body (line ~260, before the branch even runs).

The rest cover handle_run_upload, which backs POST /api/runs/upload — the entry
point the CI integration and the Playwright SDK both submit screenshots to, and
which sat entirely unexercised at 9% module coverage. A break there fails other
people's builds, not just this project's.

No AI model exists in a tmp_path workspace, so resolve_ai_model_path returns
None and these run the pixel-only decision path — the same path CI takes today.
"""
from pathlib import Path

import cv2
import numpy as np
import pytest

from visual_regression.baseline_manager import BaselineManager
from visual_regression.config import WorkspacePaths
from visual_regression.server_services import handle_ignore_regions_update, handle_run_upload


def _make_baseline(paths: WorkspacePaths, name: str) -> None:
    manager = BaselineManager(paths)
    image = paths.root.parent / "src.png"
    image.write_bytes(b"fake-png-bytes")
    manager.save_from_image(name, image, {"url": "http://example.test"})


def test_ignore_regions_update_without_run_id(tmp_path: Path):
    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    paths.ensure()
    _make_baseline(paths, "home")

    result = handle_ignore_regions_update(
        paths=paths,
        name="home",
        run_id="",
        ignore_regions=[{"x": 0, "y": 0, "width": 10, "height": 10}],
        find_selectors_fn=lambda *a, **kw: [],
        github_repo_url="",
        dashboard_base_url="http://127.0.0.1:8130",
    )

    assert result["ok"] is True
    assert result["ignore_regions"] == [{"x": 0, "y": 0, "width": 10, "height": 10}]

    manager = BaselineManager(paths)
    saved = manager.get_baseline_details("home")
    assert saved["ignore_regions"] == [{"x": 0, "y": 0, "width": 10, "height": 10}]


def test_ignore_regions_update_with_nonexistent_run_id_still_saves(tmp_path: Path):
    """run_id branch is skipped when the run dir doesn't exist, but the
    baseline-level save (the line that used to crash) must still happen."""
    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    paths.ensure()
    _make_baseline(paths, "home")

    result = handle_ignore_regions_update(
        paths=paths,
        name="home",
        run_id="does-not-exist",
        ignore_regions=[],
        find_selectors_fn=lambda *a, **kw: [],
        github_repo_url="",
        dashboard_base_url="http://127.0.0.1:8130",
    )

    assert result["ok"] is True


# ---------------------------------------------------------------------------
# handle_run_upload
# ---------------------------------------------------------------------------

def _png_bytes(color):
    image = np.full((120, 160, 3), color, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", image)
    assert ok
    return buf.tobytes()


def _png_with_patch(base, patch):
    """Same canvas with a solid block changed — a large, unambiguous mismatch."""
    image = np.full((120, 160, 3), base, dtype=np.uint8)
    image[20:90, 30:130] = patch
    ok, buf = cv2.imencode(".png", image)
    assert ok
    return buf.tobytes()


class _RecordingStore:
    def __init__(self):
        self.upserts = []

    def upsert_run_index(self, payload):
        self.upserts.append(payload)


@pytest.fixture
def workspace(tmp_path):
    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    paths.ensure()
    return paths


@pytest.fixture
def real_baseline(workspace, tmp_path):
    """A decodable baseline, unlike _make_baseline's placeholder bytes."""
    source = tmp_path / "baseline.png"
    source.write_bytes(_png_bytes((200, 200, 200)))
    BaselineManager(workspace).save_from_image(
        "home", source, {"url": "http://example.test", "updated_by": "tester", "source": "capture"}
    )
    return "home"


def _upload(workspace, tmp_path, name="home", image=None, store=None, **extra):
    parts = {
        "name": name,
        "current_image": {"content": image if image is not None else _png_bytes((200, 200, 200))},
        **extra,
    }
    return handle_run_upload(
        paths=workspace,
        project_root=tmp_path,
        parts=parts,
        github_repo_url="",
        dashboard_base_url="http://127.0.0.1:8130",
        store=store if store is not None else _RecordingStore(),
    )


class TestUploadValidation:
    def test_missing_name_is_rejected(self, workspace, tmp_path):
        with pytest.raises(ValueError, match="Missing"):
            handle_run_upload(
                paths=workspace, project_root=tmp_path,
                parts={"current_image": {"content": _png_bytes((1, 1, 1))}},
                github_repo_url="", dashboard_base_url="",
            )

    def test_missing_image_is_rejected(self, workspace, tmp_path):
        with pytest.raises(ValueError, match="Missing"):
            handle_run_upload(
                paths=workspace, project_root=tmp_path, parts={"name": "home"},
                github_repo_url="", dashboard_base_url="",
            )

    def test_unknown_baseline_is_rejected(self, workspace, tmp_path):
        with pytest.raises(FileNotFoundError, match="does not exist"):
            _upload(workspace, tmp_path, name="never-created")

    def test_undecodable_image_is_rejected(self, workspace, tmp_path, real_baseline):
        with pytest.raises(ValueError, match="could not be decoded"):
            _upload(workspace, tmp_path, image=b"this is not a PNG")


class TestUploadOutcome:
    def test_identical_upload_passes(self, workspace, tmp_path, real_baseline):
        out = _upload(workspace, tmp_path, image=_png_bytes((200, 200, 200)))
        assert out["ok"] is True
        assert out["passed"] is True
        assert out["mismatch_pct"] == pytest.approx(0.0, abs=1e-6)

    def test_changed_upload_fails(self, workspace, tmp_path, real_baseline):
        out = _upload(workspace, tmp_path, image=_png_with_patch((200, 200, 200), (20, 20, 20)))
        assert out["passed"] is False
        assert out["mismatch_pct"] > 0

    def test_a_generous_threshold_lets_a_change_pass(self, workspace, tmp_path, real_baseline):
        """threshold_pct is the caller's tolerance; at 99% nothing should fail."""
        out = _upload(
            workspace, tmp_path,
            image=_png_with_patch((200, 200, 200), (20, 20, 20)),
            threshold_pct="99",
        )
        assert out["passed"] is True

    def test_report_href_points_at_the_created_run(self, workspace, tmp_path, real_baseline):
        out = _upload(workspace, tmp_path)
        assert out["report_href"] == "/artifacts/" + out["run_id"] + "/report.html"


class TestUploadArtifacts:
    def test_writes_every_artifact_the_report_links_to(self, workspace, tmp_path, real_baseline):
        out = _upload(workspace, tmp_path, image=_png_with_patch((200, 200, 200), (20, 20, 20)))
        run_dir = workspace.runs_dir / out["run_id"]
        for artifact in ("current.webp", "diff_overlay.webp", "binary_diff.webp",
                         "report.html", "result.json"):
            assert (run_dir / artifact).exists(), "missing " + artifact

    def test_result_json_records_the_status_and_baseline(self, workspace, tmp_path, real_baseline):
        import json
        out = _upload(workspace, tmp_path, image=_png_with_patch((200, 200, 200), (20, 20, 20)))
        payload = json.loads((workspace.runs_dir / out["run_id"] / "result.json").read_text(encoding="utf-8"))
        assert payload["status"] == "FAIL"
        assert payload["baseline_name"] == "home"
        assert payload["case_name"] == "home"

    def test_run_directory_name_carries_browser_and_locale(self, workspace, tmp_path, real_baseline):
        out = _upload(workspace, tmp_path, browser="firefox", locale="zh-CN")
        assert "firefox" in out["run_id"]
        assert "zh-CN" in out["run_id"]

    def test_two_uploads_do_not_collide(self, workspace, tmp_path, real_baseline):
        first = _upload(workspace, tmp_path)
        second = _upload(workspace, tmp_path)
        assert first["run_id"] != second["run_id"]


class TestUploadParameterParsing:
    @pytest.mark.parametrize("field", ["threshold_pct", "pixel_threshold", "min_region_area"])
    def test_unparseable_numbers_fall_back_to_defaults(self, workspace, tmp_path, real_baseline, field):
        """A malformed value must not 500 the endpoint."""
        out = _upload(workspace, tmp_path, **{field: "not-a-number"})
        assert out["ok"] is True

    def test_inline_ignore_regions_are_applied(self, workspace, tmp_path, real_baseline):
        changed = _png_with_patch((200, 200, 200), (20, 20, 20))
        without = _upload(workspace, tmp_path, image=changed)
        with_region = _upload(workspace, tmp_path, image=changed, ignore_region="25,15,115,85")
        assert with_region["mismatch_pct"] < without["mismatch_pct"]

    def test_saved_baseline_regions_are_used_when_none_are_supplied(self, workspace, tmp_path, real_baseline):
        changed = _png_with_patch((200, 200, 200), (20, 20, 20))
        before = _upload(workspace, tmp_path, image=changed)

        BaselineManager(workspace).save_ignore_regions(
            "home", [{"x": 25, "y": 15, "width": 115, "height": 85}]
        )
        after = _upload(workspace, tmp_path, image=changed)

        assert after["mismatch_pct"] < before["mismatch_pct"]


class TestUploadIndexing:
    def test_run_is_indexed_with_a_resolvable_run_id(self, workspace, tmp_path, real_baseline):
        """result.json carries no run id of its own; without the injected
        run_id, upsert_run_index silently no-ops and the run never appears."""
        store = _RecordingStore()
        out = _upload(workspace, tmp_path, store=store)
        assert len(store.upserts) == 1
        assert store.upserts[0]["run_id"] == out["run_id"]

    def test_a_failing_store_does_not_fail_the_upload(self, workspace, tmp_path, real_baseline):
        class _BrokenStore:
            def upsert_run_index(self, payload):
                raise RuntimeError("database is down")

        out = _upload(workspace, tmp_path, store=_BrokenStore())
        assert out["ok"] is True


class TestIgnoreRegionsRecompute:
    def test_updating_regions_recomputes_the_existing_run(self, workspace, tmp_path, real_baseline):
        """The point of the feature: masking the changed area should flip a
        previously failing run to PASS and rewrite its result.json."""
        import json
        upload = _upload(workspace, tmp_path, image=_png_with_patch((200, 200, 200), (20, 20, 20)))
        assert upload["passed"] is False
        result_file = workspace.runs_dir / upload["run_id"] / "result.json"

        handle_ignore_regions_update(
            paths=workspace, name="home", run_id=upload["run_id"],
            ignore_regions=[{"x": 25, "y": 15, "width": 115, "height": 85}],
            find_selectors_fn=lambda *a, **k: [], github_repo_url="", dashboard_base_url="",
            store=_RecordingStore(),
        )

        payload = json.loads(result_file.read_text(encoding="utf-8"))
        assert payload["status"] == "PASS"
        assert payload["result"]["mismatch_pct"] == pytest.approx(0.0, abs=1e-6)

    def test_recompute_reindexes_the_run(self, workspace, tmp_path, real_baseline):
        upload = _upload(workspace, tmp_path, image=_png_with_patch((200, 200, 200), (20, 20, 20)))
        store = _RecordingStore()

        handle_ignore_regions_update(
            paths=workspace, name="home", run_id=upload["run_id"],
            ignore_regions=[{"x": 25, "y": 15, "width": 115, "height": 85}],
            find_selectors_fn=lambda *a, **k: [], github_repo_url="", dashboard_base_url="",
            store=store,
        )

        assert store.upserts[-1]["run_id"] == upload["run_id"]
        assert store.upserts[-1]["status"] == "PASS"

    def test_recompute_regenerates_the_html_report(self, workspace, tmp_path, real_baseline):
        upload = _upload(workspace, tmp_path, image=_png_with_patch((200, 200, 200), (20, 20, 20)))
        report = workspace.runs_dir / upload["run_id"] / "report.html"
        before = report.read_text(encoding="utf-8")

        handle_ignore_regions_update(
            paths=workspace, name="home", run_id=upload["run_id"],
            ignore_regions=[{"x": 25, "y": 15, "width": 115, "height": 85}],
            find_selectors_fn=lambda *a, **k: [], github_repo_url="", dashboard_base_url="",
            store=_RecordingStore(),
        )

        assert report.read_text(encoding="utf-8") != before
