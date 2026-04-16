from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .config import WorkspacePaths


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BaselineManager:
    def __init__(self, paths: WorkspacePaths):
        self.paths = paths
        self.paths.ensure()

    @staticmethod
    def normalize_name(name: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", name.strip())
        safe = safe.strip("_.")
        if not safe:
            raise ValueError("Invalid baseline name. Use letters, numbers, dot, dash, underscore.")
        return safe

    def baseline_dir(self, name: str) -> Path:
        return self.paths.baselines_dir / self.normalize_name(name)

    def baseline_image_path(self, name: str) -> Path:
        return self.baseline_dir(name) / "baseline.png"

    def metadata_path(self, name: str) -> Path:
        return self.baseline_dir(name) / "metadata.json"

    def versions_dir(self, name: str) -> Path:
        return self.baseline_dir(name) / "versions"

    def latest_version_manifest_path(self, name: str) -> Path:
        return self.versions_dir(name) / "manifest.json"

    def exists(self, name: str) -> bool:
        return self.baseline_image_path(name).exists()

    def _archive_existing_baseline(self, name: str, previous_meta: Dict[str, Any]) -> None:
        baseline_image = self.baseline_image_path(name)
        metadata_file = self.metadata_path(name)
        if not baseline_image.exists() or not metadata_file.exists():
            return

        versions_dir = self.versions_dir(name)
        versions_dir.mkdir(parents=True, exist_ok=True)
        version_stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        version_dir = versions_dir / version_stamp
        version_dir.mkdir(parents=True, exist_ok=True)

        shutil.copy2(baseline_image, version_dir / "baseline.png")
        shutil.copy2(metadata_file, version_dir / "metadata.json")

        manifest_path = self.latest_version_manifest_path(name)
        manifest: List[Dict[str, Any]] = []
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.append(
            {
                "version": version_stamp,
                "archived_at": _utc_now(),
                "source_updated_at": previous_meta.get("updated_at"),
                "source_created_at": previous_meta.get("created_at"),
            }
        )
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    def save_from_image(self, name: str, source_image_path: Path, capture_meta: Dict[str, Any]) -> None:
        target_dir = self.baseline_dir(name)
        target_dir.mkdir(parents=True, exist_ok=True)

        target_image = self.baseline_image_path(name)
        metadata_file = self.metadata_path(name)
        now = _utc_now()

        previous_meta: Dict[str, Any] = {}
        if metadata_file.exists():
            previous_meta = self.load_metadata(name)
            self._archive_existing_baseline(name, previous_meta)

        shutil.copy2(source_image_path, target_image)

        history = previous_meta.get("history", [])
        history.append(
            {
                "timestamp": now,
                "actor": capture_meta.get("updated_by") or capture_meta.get("reviewer") or "system",
                "source": capture_meta.get("source", "capture"),
                "url": capture_meta.get("url"),
            }
        )
        metadata = {
            "name": self.normalize_name(name),
            "created_at": previous_meta.get("created_at", now),
            "updated_at": now,
            "capture": capture_meta,
            "history": history[-25:],
        }
        metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    def load_metadata(self, name: str) -> Dict[str, Any]:
        path = self.metadata_path(name)
        if not path.exists():
            raise FileNotFoundError(f"metadata not found for baseline '{name}'")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_baselines(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for child in sorted(self.paths.baselines_dir.iterdir()):
            if not child.is_dir():
                continue
            image_path = child / "baseline.png"
            metadata_path = child / "metadata.json"
            if not image_path.exists() or not metadata_path.exists():
                continue
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
            manifest_path = child / "versions" / "manifest.json"
            version_count = 0
            if manifest_path.exists():
                try:
                    version_count = len(json.loads(manifest_path.read_text(encoding="utf-8")))
                except Exception:
                    version_count = 0
            items.append(
                {
                    "name": data.get("name", child.name),
                    "created_at": data.get("created_at"),
                    "updated_at": data.get("updated_at"),
                    "url": data.get("capture", {}).get("url"),
                    "browser": data.get("capture", {}).get("browser"),
                    "device": data.get("capture", {}).get("device"),
                    "locale": data.get("capture", {}).get("locale"),
                    "timezone_id": data.get("capture", {}).get("timezone_id"),
                    "viewport": data.get("capture", {}).get("viewport"),
                    "thumbnail_href": f"/baseline/{child.name}/baseline.png",
                    "version_count": version_count,
                    "history": data.get("history", []),
                }
            )
        return items

    def get_baseline_details(self, name: str) -> Dict[str, Any]:
        baseline_name = self.normalize_name(name)
        data = self.load_metadata(baseline_name)
        versions_manifest: List[Dict[str, Any]] = []
        manifest_path = self.latest_version_manifest_path(baseline_name)
        if manifest_path.exists():
            versions_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        versions = []
        for version in reversed(versions_manifest):
            version_id = version.get("version")
            if not version_id:
                continue
            versions.append(
                {
                    **version,
                    "image_href": f"/baseline/{baseline_name}/versions/{version_id}/baseline.png",
                    "metadata_href": f"/baseline/{baseline_name}/versions/{version_id}/metadata.json",
                }
            )

        return {
            "name": baseline_name,
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "capture": data.get("capture", {}),
            "history": data.get("history", []),
            "current_image_href": f"/baseline/{baseline_name}/baseline.png",
            "metadata_href": f"/baseline/{baseline_name}/metadata.json",
            "versions": versions,
        }

    def delete_baseline(self, name: str) -> Dict[str, Any]:
        baseline_name = self.normalize_name(name)
        target_dir = self.baseline_dir(baseline_name).resolve()
        baselines_root = self.paths.baselines_dir.resolve()
        if baselines_root not in target_dir.parents:
            raise ValueError("Refusing to delete a baseline outside the baselines directory")
        if not target_dir.exists():
            raise FileNotFoundError(f"Baseline '{baseline_name}' not found")
        shutil.rmtree(target_dir)
        return {"name": baseline_name, "deleted": True}

    def restore_version(self, name: str, version: str, restored_by: str | None = None) -> Dict[str, Any]:
        baseline_name = self.normalize_name(name)
        version_id = str(version).strip()
        if not version_id:
            raise ValueError("version is required")

        version_dir = self.versions_dir(baseline_name) / version_id
        version_image = version_dir / "baseline.png"
        version_metadata = version_dir / "metadata.json"
        if not version_image.exists() or not version_metadata.exists():
            raise FileNotFoundError(f"Version '{version_id}' not found for baseline '{baseline_name}'")

        current_meta = self.load_metadata(baseline_name)
        self._archive_existing_baseline(baseline_name, current_meta)

        shutil.copy2(version_image, self.baseline_image_path(baseline_name))
        restored_meta = json.loads(version_metadata.read_text(encoding="utf-8"))
        now = _utc_now()
        history = current_meta.get("history", [])
        history.append(
            {
                "timestamp": now,
                "actor": restored_by or "system",
                "source": "restore",
                "url": restored_meta.get("capture", {}).get("url"),
                "version": version_id,
            }
        )
        payload = {
            "name": baseline_name,
            "created_at": current_meta.get("created_at", restored_meta.get("created_at", now)),
            "updated_at": now,
            "capture": restored_meta.get("capture", {}),
            "history": history[-25:],
            "restored_from_version": version_id,
        }
        self.metadata_path(baseline_name).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {
            "name": baseline_name,
            "restored_version": version_id,
            "restored_by": restored_by or "system",
            "updated_at": now,
        }
