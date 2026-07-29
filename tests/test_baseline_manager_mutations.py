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
    _write_png(old_version_dir / "baseline.webp", b"restored")
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


def test_rapid_consecutive_updates_do_not_overwrite_archived_versions(tmp_path: Path, monkeypatch):
    """Regression test: version_stamp only has second precision, so two
    archives within the same second used to collide on the same directory
    name and mkdir(exist_ok=True) would silently overwrite the first
    archive's image/metadata with the second one's, destroying that
    version's history while leaving a stale duplicate manifest entry."""
    import visual_regression.baseline_manager as bm_module

    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    manager = BaselineManager(paths)

    image_v1 = tmp_path / "v1.png"
    image_v1.write_bytes(b"version-1-content")
    manager.save_from_image("sample", image_v1, {"url": "https://example.com", "browser": "chromium"})

    # Freeze "now" so both updates land in the same second, forcing a collision.
    frozen_now = bm_module.datetime(2026, 1, 1, 12, 0, 0, tzinfo=bm_module.timezone.utc)

    class _FrozenDateTime(bm_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen_now

    monkeypatch.setattr(bm_module, "datetime", _FrozenDateTime)

    image_v2 = tmp_path / "v2.png"
    image_v2.write_bytes(b"version-2-content")
    manager.save_from_image("sample", image_v2, {"url": "https://example.com", "browser": "chromium"})

    image_v3 = tmp_path / "v3.png"
    image_v3.write_bytes(b"version-3-content")
    manager.save_from_image("sample", image_v3, {"url": "https://example.com", "browser": "chromium"})

    versions_dir = manager.versions_dir("sample")
    subdirs = sorted(p.name for p in versions_dir.iterdir() if p.is_dir())
    assert len(subdirs) == 2, f"expected 2 distinct archived version directories, got {subdirs}"

    contents = set()
    for sub in subdirs:
        contents.add((versions_dir / sub / "baseline.png").read_bytes())
    assert contents == {b"version-1-content", b"version-2-content"}, (
        "both archived versions must keep their own distinct content, not have one overwritten by the other"
    )
