"""_load_public_dataset_images used to raise ZeroDivisionError when the
manifest's "images" list was empty (a valid but data-less manifest, e.g. one
written before any images were actually downloaded/scanned) and a caller
passed max_images — `by_source` groups items by source, and an empty images
list means an empty `by_source`, so `max_images // len(by_source)` divided
by zero instead of returning an empty image list.
"""
import json
from pathlib import Path

from visual_regression.dataset_generator import _load_public_dataset_images


def test_empty_manifest_with_max_images_returns_empty_list_not_crash(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"images": []}), encoding="utf-8")

    result = _load_public_dataset_images(manifest_path, max_images=100)

    assert result == []


def test_empty_manifest_without_max_images_returns_empty_list(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"images": []}), encoding="utf-8")

    result = _load_public_dataset_images(manifest_path, max_images=None)

    assert result == []
