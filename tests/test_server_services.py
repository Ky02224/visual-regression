"""Regression test for handle_ignore_regions_update.

It used to crash with `UnboundLocalError: cannot access local variable
'BaselineManager' where it is not associated with a value` on every call: a
redundant `from .baseline_manager import BaselineManager` deep inside the
function's `if run_id:` branch made Python treat the name as local for the
*entire* function, shadowing the module-level import used earlier in the
same function body (line ~260, before the branch even runs).
"""
from pathlib import Path

from visual_regression.baseline_manager import BaselineManager
from visual_regression.config import WorkspacePaths
from visual_regression.server_services import handle_ignore_regions_update


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
