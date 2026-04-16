from pathlib import Path

from visual_regression.ai_datasets import build_public_dataset_manifest, scan_public_dataset
from visual_regression.config import WorkspacePaths


def test_scan_public_dataset_reads_images_and_split(tmp_path: Path):
    root = tmp_path / "webui" / "train"
    root.mkdir(parents=True)
    (root / "screen-1.png").write_bytes(b"fake")
    (root / "ignore.txt").write_text("nope", encoding="utf-8")

    records = scan_public_dataset("webui", tmp_path / "webui")
    assert len(records) == 1
    assert records[0].source == "webui"
    assert records[0].split == "train"


def test_build_public_dataset_manifest_combines_sources(tmp_path: Path):
    webui_dir = tmp_path / "webui"
    rico_dir = tmp_path / "rico" / "test"
    webui_dir.mkdir(parents=True)
    rico_dir.mkdir(parents=True)
    (webui_dir / "a.png").write_bytes(b"png")
    (rico_dir / "b.jpg").write_bytes(b"jpg")

    paths = WorkspacePaths(root=tmp_path / ".visual-regression")
    manifest = build_public_dataset_manifest(
        paths=paths,
        webui_dir=webui_dir,
        rico_dir=tmp_path / "rico",
        max_images_per_source=10,
    )
    assert manifest["total_images"] == 2
    assert manifest["sources"]["webui"]["count"] == 1
    assert manifest["sources"]["rico"]["count"] == 1
