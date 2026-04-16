from pathlib import Path

from visual_regression.baseline_manager import BaselineManager
from visual_regression.config import WorkspacePaths


def _write_png(path: Path, content: bytes = b"png") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_delete_baseline_removes_directory(tmp_path: Path):
    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    manager = BaselineManager(paths)
    baseline_dir = manager.baseline_dir("sample")
    _write_png(baseline_dir / "baseline.png")
    manager.metadata_path("sample").write_text('{"name":"sample"}', encoding="utf-8")

    result = manager.delete_baseline("sample")

    assert result["deleted"] is True
    assert not baseline_dir.exists()


def test_restore_version_replaces_current_baseline_and_updates_history(tmp_path: Path):
    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    manager = BaselineManager(paths)

    current_image = tmp_path / "current.png"
    current_image.write_bytes(b"current")
    manager.save_from_image(
        "sample",
        current_image,
        {"url": "https://current.example", "browser": "chromium", "updated_by": "qa"},
    )

    old_version_dir = manager.versions_dir("sample") / "old-version"
    _write_png(old_version_dir / "baseline.png", b"restored")
    (old_version_dir / "metadata.json").write_text(
        '{"name":"sample","capture":{"url":"https://old.example","browser":"firefox"}}',
        encoding="utf-8",
    )

    result = manager.restore_version("sample", "old-version", restored_by="lead")
    restored_meta = manager.load_metadata("sample")

    assert result["restored_version"] == "old-version"
    assert manager.baseline_image_path("sample").read_bytes() == b"restored"
    assert restored_meta["capture"]["url"] == "https://old.example"
    assert restored_meta["history"][-1]["source"] == "restore"
    assert restored_meta["history"][-1]["actor"] == "lead"
