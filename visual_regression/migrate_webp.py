"""One-time migration: convert legacy .png baseline images to .webp.

Baselines captured before the WebP migration are still served correctly via
the .webp -> .png fallback in resolve_image_path(), so this is optional —
it exists purely to reclaim the disk-space savings WebP was introduced for.

Only touches baselines/<name>/baseline.png and their archived
baselines/<name>/versions/<id>/baseline.png copies. Run artifacts
(runs/<id>/*.png) are left alone: they're read-only historical records that
nothing ever re-writes, so migrating them buys nothing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import cv2
import numpy as np

from .config import WorkspacePaths

# WebP encodes width/height as 14-bit fields, so it hard-caps both dimensions
# at 16383px. Full-page screenshots of long pages can exceed that — those
# stay .png (matching what a fresh capture of the same page would produce).
_WEBP_MAX_DIMENSION = 16383


def _migrate_one(directory: Path, dry_run: bool) -> Dict[str, Any]:
    """Convert directory/baseline.png to directory/baseline.webp.

    Returns a result dict with "status": "converted" | "skipped" | "failed".
    """
    webp_path = directory / "baseline.webp"
    png_path = directory / "baseline.png"

    if webp_path.exists():
        return {"path": str(png_path if png_path.exists() else webp_path), "status": "skipped", "reason": "already .webp"}
    if not png_path.exists():
        return {"path": str(directory), "status": "skipped", "reason": "no baseline.png"}

    try:
        img = cv2.imread(str(png_path), cv2.IMREAD_COLOR)
        if img is None:
            return {"path": str(png_path), "status": "failed", "reason": "cv2.imread returned None"}

        h, w = img.shape[:2]
        if h > _WEBP_MAX_DIMENSION or w > _WEBP_MAX_DIMENSION:
            return {
                "path": str(png_path), "status": "skipped",
                "reason": f"{w}x{h} exceeds WebP's {_WEBP_MAX_DIMENSION}px dimension limit",
            }

        ok, buf = cv2.imencode(".webp", img, [cv2.IMWRITE_WEBP_QUALITY, 90])
        if not ok:
            return {"path": str(png_path), "status": "failed", "reason": "cv2.imencode failed"}

        # Verify the encoded bytes actually decode back to the same image
        # before touching anything on disk.
        webp_bytes = buf.tobytes()
        verify = cv2.imdecode(np.frombuffer(webp_bytes, np.uint8), cv2.IMREAD_COLOR)
        if verify is None or verify.shape != img.shape:
            return {"path": str(png_path), "status": "failed", "reason": "round-trip verification failed"}

        original_size = png_path.stat().st_size
        if dry_run:
            return {
                "path": str(png_path), "status": "converted", "dry_run": True,
                "original_bytes": original_size, "new_bytes": len(webp_bytes),
            }

        webp_path.write_bytes(webp_bytes)
        png_path.unlink()
        return {
            "path": str(png_path), "status": "converted", "dry_run": False,
            "original_bytes": original_size, "new_bytes": len(webp_bytes),
        }
    except Exception as e:
        return {"path": str(png_path), "status": "failed", "reason": str(e)}


def migrate_baselines_to_webp(paths: WorkspacePaths, dry_run: bool = False) -> Dict[str, List[Dict[str, Any]]]:
    """Convert every legacy baseline.png (current + archived versions) to .webp.

    Safe to re-run: already-migrated baselines are skipped. With dry_run=True,
    nothing on disk is modified — results still report what *would* happen.
    """
    results: List[Dict[str, Any]] = []

    baselines_dir = paths.baselines_dir
    if not baselines_dir.exists():
        return {"converted": [], "skipped": [], "failed": []}

    for baseline_dir in sorted(baselines_dir.iterdir()):
        if not baseline_dir.is_dir():
            continue
        results.append(_migrate_one(baseline_dir, dry_run))

        versions_dir = baseline_dir / "versions"
        if versions_dir.exists():
            for version_dir in sorted(versions_dir.iterdir()):
                if version_dir.is_dir():
                    results.append(_migrate_one(version_dir, dry_run))

    return {
        "converted": [r for r in results if r["status"] == "converted"],
        "skipped": [r for r in results if r["status"] == "skipped"],
        "failed": [r for r in results if r["status"] == "failed"],
    }
