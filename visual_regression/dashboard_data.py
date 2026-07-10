from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

from .baseline_manager import BaselineManager
from .config import WorkspacePaths
from ._json_cache import JsonCache


# Server-side dashboard cache with TTL (60 seconds)
class _DashboardCache:
    _cache: Dict[str, Any] | None = None
    _cache_time: float = 0.0
    _TTL_SECONDS: int = 60
    
    @classmethod
    def get(cls, paths: WorkspacePaths) -> Dict[str, Any] | None:
        """Get cached dashboard snapshot if still valid (TTL not expired)."""
        if cls._cache is None:
            return None
        if time.time() - cls._cache_time > cls._TTL_SECONDS:
            cls._cache = None
            return None
        return cls._cache
    
    @classmethod
    def set(cls, snapshot: Dict[str, Any]) -> None:
        """Cache dashboard snapshot with current timestamp."""
        cls._cache = snapshot
        cls._cache_time = time.time()
    
    @classmethod
    def invalidate(cls) -> None:
        """Invalidate cache (called after POST actions)."""
        cls._cache = None
        cls._cache_time = 0.0


def _latest_suite_summary(paths: WorkspacePaths) -> Dict[str, Any] | None:
    summaries = sorted(paths.reports_dir.glob("suite-summary-*.json"), reverse=True)
    for path in summaries:
        try:
            return JsonCache.read(path)
        except Exception:
            continue
    return None


def _recent_suite_summaries(paths: WorkspacePaths, limit: int = 6) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for path in sorted(paths.reports_dir.glob("suite-summary-*.json"), reverse=True)[:limit]:
        try:
            payload = JsonCache.read(path)
        except Exception:
            continue
        payload["file"] = path.name
        items.append(payload)
    return items


def _load_model_metadata(paths: WorkspacePaths) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for path in sorted(paths.models_dir.glob("*.json"), reverse=True):
        try:
            payload = JsonCache.read(path)
        except Exception:
            continue
        payload["name"] = path.name
        items.append(payload)
    return items


def _load_all_baselines_indexed(paths: WorkspacePaths) -> Dict[str, Dict[str, Any]]:
    """
    Load all baseline metadata once and index by name.
    
    This prevents N+1 lookups when processing runs.
    
    Returns:
        Dict mapping baseline name to its details (same format as get_baseline_details).
    """
    baseline_manager = BaselineManager(paths)
    indexed: Dict[str, Dict[str, Any]] = {}
    
    for child in sorted(paths.baselines_dir.iterdir()):
        if not child.is_dir():
            continue
        image_path = child / "baseline.png"
        metadata_path = child / "metadata.json"
        if not image_path.exists() or not metadata_path.exists():
            continue
        
        try:
            data = JsonCache.read(metadata_path)
            baseline_name = data.get("name", child.name)
            
            # Load version manifest
            versions_manifest: List[Dict[str, Any]] = []
            manifest_path = child / "versions" / "manifest.json"
            if manifest_path.exists():
                versions_manifest = JsonCache.read(manifest_path)
            
            # Build versions list
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
            
            # Build baseline details entry
            indexed[baseline_name] = {
                "name": baseline_name,
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
                "capture": data.get("capture", {}),
                "history": data.get("history", []),
                # Convenience top-level fields for dashboard filters
                "browser": data.get("capture", {}).get("browser"),
                "device": data.get("capture", {}).get("device"),
                "locale": data.get("capture", {}).get("locale"),
                "current_image_href": f"/baseline/{baseline_name}/baseline.png",
                "metadata_href": f"/baseline/{baseline_name}/metadata.json",
                "versions": versions,
                "version_count": len(versions),
            }
        except Exception:
            continue
    
    return indexed


def _load_runs(paths: WorkspacePaths, baselines_indexed: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Load all runs with their metadata.
    
    Args:
        paths: WorkspacePaths instance
        baselines_indexed: Pre-loaded baseline details indexed by name (prevents N+1)
    
    Returns:
        List of run metadata dictionaries
    """
    runs: List[Dict[str, Any]] = []
    for run_dir in sorted(paths.runs_dir.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        result_file = run_dir / "result.json"
        if not result_file.exists():
            continue
        try:
            payload = JsonCache.read(result_file)
        except Exception:
            continue

        result = payload.get("result", {})
        ai_assessment = payload.get("ai_assessment", {})
        decision = payload.get("decision") or payload.get("review", {})
        capture = payload.get("capture", {})
        severity = payload.get("severity", {})
        baseline_name = payload.get("baseline_name") or payload.get("case_name")
        
        # Look up baseline from pre-loaded index (O(1) lookup, no file I/O)
        baseline_details = baselines_indexed.get(baseline_name) if baseline_name else None
        
        runs.append(
            {
                "run": run_dir.name,
                "id": run_dir.name,
                "case_name": payload.get("case_name"),
                "name": payload.get("case_name"),
                "status": payload.get("status"),
                "decision_status": decision.get("status"),
                "decider": decision.get("reviewer") or decision.get("decider"),
                "decision_comment": decision.get("comment"),
                "decided_at": decision.get("timestamp"),
                "mismatch_pct": result.get("mismatch_pct"),
                "mismatch": result.get("mismatch_pct"),
                "diff_regions": len(result.get("regions", [])),
                "ai_label": ai_assessment.get("label"),
                "ai_score": ai_assessment.get("score"),
                "ai_explanation": payload.get("ai_explanation"),
                "severity": severity,
                "locale": capture.get("locale"),
                "browser": capture.get("browser"),
                "device": capture.get("device"),
                "url": capture.get("url"),
                "baseline_name": baseline_name,
                "baseline_image_href": baseline_details.get("current_image_href") if baseline_details else None,
                "suite_name": payload.get("suite_name"),
                "report_href": f"/artifacts/{run_dir.name}/report.html",
            }
        )
    return runs


def build_dashboard_snapshot(project_root: Path, paths: WorkspacePaths) -> Dict[str, Any]:
    """
    Build complete dashboard snapshot with caching.
    
    This function:
    - Returns cached result if TTL not expired (60 seconds)
    - Loads all baselines once and indexes them (prevents N+1 lookups)
    - Uses JsonCache for JSON reads to minimize file I/O
    - Caches the complete snapshot for fast API responses
    
    Args:
        project_root: Root project directory
        paths: WorkspacePaths instance
        
    Returns:
        Dashboard snapshot dictionary
    """
    paths.ensure()
    
    # Check cache first (TTL-based)
    cached = _DashboardCache.get(paths)
    if cached is not None:
        return cached
    
    # Load all baselines at once (O(n) instead of O(n×m))
    baselines_indexed = _load_all_baselines_indexed(paths)
    baselines = list(baselines_indexed.values())
    
    # Load runs with pre-indexed baselines (prevents N+1)
    runs = _load_runs(paths, baselines_indexed)
    
    models = _load_model_metadata(paths)
    latest_suite = _latest_suite_summary(paths)
    recent_summaries = _recent_suite_summaries(paths)
    
    # Compute filter values from runs and baselines
    # For runs, fields are at the top-level; for baselines, capture info is nested under "capture".
    browser_values = {item.get("browser") for item in runs if item.get("browser")}
    browser_values.update(item.get("capture", {}).get("browser") for item in baselines if item.get("capture", {}).get("browser"))
    locale_values = {item.get("locale") for item in runs if item.get("locale")}
    locale_values.update(item.get("capture", {}).get("locale") for item in baselines if item.get("capture", {}).get("locale"))
    device_values = {item.get("device") or "desktop" for item in runs if item.get("browser")}
    device_values.update((item.get("capture", {}).get("device") or "desktop") for item in baselines if item.get("capture", {}).get("browser"))

    metrics = {
        "baseline_count": len(baselines),
        "run_count": len(runs),
        "failed_runs": sum(1 for item in runs if item.get("status") == "FAIL"),
        "pending_decisions": sum(1 for item in runs if (item.get("decision_status") or "pending") == "pending"),
        "approved_decisions": sum(1 for item in runs if item.get("decision_status") == "approved"),
        "model_count": len(models),
        "browser_coverage": len(browser_values),
        "device_coverage": len(device_values),
        "locale_coverage": len(locale_values),
    }

    snapshot = {
        "project_root": str(project_root),
        "metrics": metrics,
        **metrics,
        "baselines": baselines,
        "runs": runs,
        "models": models,
        "latest_suite": latest_suite,
        "recent_summaries": recent_summaries,
    }
    
    # Cache result
    _DashboardCache.set(snapshot)
    return snapshot
