from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
KNOWN_SOURCES = ("webui", "rico", "screen-annotation")


@dataclass
class PublicImageRecord:
    source: str
    path: str
    split: str | None = None

    def to_dict(self) -> Dict[str, str]:
        payload: Dict[str, str] = {"source": self.source, "path": self.path}
        if self.split:
            payload["split"] = self.split
        return payload


def _iter_images(root: Path, limit: int | None = None) -> Iterable[Path]:
    count = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        yield path
        count += 1
        if limit is not None and count >= limit:
            return


def _infer_split(path: Path) -> str | None:
    lowered = [part.lower() for part in path.parts]
    for candidate in ("train", "training", "val", "valid", "validation", "test", "testing"):
        if candidate in lowered:
            if candidate.startswith("val") or candidate == "valid":
                return "val"
            if candidate.startswith("test"):
                return "test"
            return "train"
    return None


def scan_public_dataset(source: str, root: Path, limit: int | None = None) -> List[PublicImageRecord]:
    if source not in KNOWN_SOURCES:
        raise ValueError(f"Unknown dataset source '{source}'. Expected one of: {', '.join(KNOWN_SOURCES)}")
    if not root.exists():
        raise FileNotFoundError(f"Dataset directory not found: {root}")

    records: List[PublicImageRecord] = []
    for image_path in _iter_images(root, limit=limit):
        records.append(
            PublicImageRecord(
                source=source,
                path=str(image_path.resolve()),
                split=_infer_split(image_path.relative_to(root)),
            )
        )
    return records


def build_public_dataset_manifest(
    paths,
    webui_dir: Path | None = None,
    rico_dir: Path | None = None,
    screen_annotation_dir: Path | None = None,
    max_images_per_source: int = 250,
) -> Dict[str, object]:
    records: List[PublicImageRecord] = []
    sources: Dict[str, Dict[str, object]] = {}

    for source, root in (
        ("webui", webui_dir),
        ("rico", rico_dir),
        ("screen-annotation", screen_annotation_dir),
    ):
        if root is None:
            continue
        found = scan_public_dataset(source, root, limit=max_images_per_source)
        records.extend(found)
        sources[source] = {
            "root": str(root.resolve()),
            "count": len(found),
        }

    manifest = {
        "sources": sources,
        "images": [record.to_dict() for record in records],
        "total_images": len(records),
    }
    return manifest


def save_public_dataset_manifest(paths, manifest: Dict[str, object], filename: str = "public-ui-manifest.json") -> Path:
    paths.ensure()
    target = paths.datasets_dir / filename
    target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return target


def load_public_dataset_manifest(manifest_path: Path) -> Dict[str, object]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload.setdefault("sources", {})
    payload.setdefault("images", [])
    payload.setdefault("total_images", len(payload["images"]))
    return payload

