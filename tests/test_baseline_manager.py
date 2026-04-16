import json
from pathlib import Path

from visual_regression.baseline_manager import BaselineManager
from visual_regression.config import WorkspacePaths


def test_baseline_versioning_and_details(tmp_path: Path):
    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    paths.ensure()
    manager = BaselineManager(paths)

    first_image = tmp_path / "first.png"
    second_image = tmp_path / "second.png"
    first_image.write_bytes(b"first")
    second_image.write_bytes(b"second")

    manager.save_from_image(
        "home",
        first_image,
        {"url": "http://example.test", "updated_by": "Alice", "source": "capture"},
    )
    manager.save_from_image(
        "home",
        second_image,
        {"url": "http://example.test/new", "updated_by": "Bob", "source": "refresh"},
    )

    listing = manager.list_baselines()
    assert listing[0]["version_count"] == 1
    assert listing[0]["thumbnail_href"].endswith("/baseline/home/baseline.png")
    assert len(listing[0]["history"]) == 2

    details = manager.get_baseline_details("home")
    assert details["current_image_href"].endswith("/baseline/home/baseline.png")
    assert len(details["versions"]) == 1
    assert details["versions"][0]["image_href"].endswith("/baseline/home/versions/" + details["versions"][0]["version"] + "/baseline.png")
    assert details["history"][-1]["actor"] == "Bob"
