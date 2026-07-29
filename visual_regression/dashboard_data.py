from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

from .baseline_manager import BaselineManager
from .config import WorkspacePaths
from ._json_cache import JsonCache


# Server-side dashboard cache with TTL (60 seconds)
class _DashboardCache:
    _lock = threading.Lock()
    # Cache maps workspace_root_str -> (snapshot_dict, cache_time_float)
    _caches: Dict[str, tuple[Dict[str, Any], float]] = {}
    _TTL_SECONDS: int = 60
    
    @classmethod
    def get(cls, paths: WorkspacePaths) -> Dict[str, Any] | None:
        """Get cached dashboard snapshot if still valid (TTL not expired)."""
        key = str(paths.root.resolve())
        with cls._lock:
            cached = cls._caches.get(key)
            if cached is None:
                return None
            snapshot, cache_time = cached
            if time.time() - cache_time > cls._TTL_SECONDS:
                cls._caches.pop(key, None)
                return None
            return snapshot
    
    @classmethod
    def set(cls, paths: WorkspacePaths, snapshot: Dict[str, Any]) -> None:
        """Cache dashboard snapshot with current timestamp."""
        key = str(paths.root.resolve())
        with cls._lock:
            cls._caches[key] = (snapshot, time.time())
    
    @classmethod
    def invalidate(cls, paths: WorkspacePaths | None = None) -> None:
        """Invalidate cache (called after POST actions)."""
        with cls._lock:
            if paths is not None:
                key = str(paths.root.resolve())
                cls._caches.pop(key, None)
            else:
                cls._caches.clear()


def _sanitize_ai_label(label: str | None) -> str | None:
    """Drop deprecated / empty labels so UI shows no ChangeTypeBadge."""
    if not label:
        return None
    normalized = str(label).strip().lower().replace("_", "-")
    if normalized in {"insignificant-change", "meaningful-change", "no-defect", "none"}:
        return None
    return str(label).strip()


def _normalize_review_status(
    raw_status: str | None,
    decision_status: str | None,
    mismatch_pct: float | None = None,
    threshold_pct: float | None = None,
) -> str:
    """Percy-style review state: no_changes | unreviewed | approved | rejected."""
    decision = str(decision_status or "pending").strip().lower()
    if decision == "approved":
        return "approved"
    if decision == "rejected":
        return "rejected"
    if raw_status == "PASS":
        return "no_changes"
    if raw_status == "FAIL":
        return "unreviewed"
    threshold = float(threshold_pct if threshold_pct is not None else 0.5)
    mismatch = float(mismatch_pct or 0.0)
    if mismatch <= threshold:
        return "no_changes"
    return "unreviewed"


def _normalize_run_status(raw_status: str | None, decision_status: str | None) -> str:
    """Legacy status field for suite summaries / CI (maps review state)."""
    review = _normalize_review_status(raw_status, decision_status)
    if review == "no_changes":
        return "passed"
    if review == "unreviewed":
        return "attention"
    if review == "rejected":
        return "failed"
    return "passed"


def _latest_suite_summary(paths: WorkspacePaths, runs: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    items = _recent_suite_summaries(paths, runs, limit=1)
    return items[0] if items else None


def _recent_suite_summaries(paths: WorkspacePaths, runs: List[Dict[str, Any]], limit: int = 6) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    # Map run_id to its dynamic review status
    run_status_map: Dict[str, str] = {r["id"]: r["review_status"] for r in runs}
    
    for path in sorted(paths.reports_dir.glob("suite-summary-*.json"), reverse=True)[:limit]:
        try:
            payload = JsonCache.read(path)
            cases = payload.get("cases", [])
            passed_count = 0
            failed_count = 0
            
            for case in cases:
                report_path = case.get("report", "")
                run_id = ""
                if report_path:
                    parts = Path(report_path).parts
                    if len(parts) >= 2:
                        run_id = parts[-2]
                        
                if run_id and run_id in run_status_map:
                    rev_status = run_status_map[run_id]
                    if rev_status in ("approved", "no_changes"):
                        passed_count += 1
                    else:
                        failed_count += 1
                else:
                    if case.get("status") == "PASS":
                        passed_count += 1
                    else:
                        failed_count += 1
                        
            payload["passed"] = passed_count
            payload["failed"] = failed_count
            payload["status"] = "passed" if failed_count == 0 else "failed"
            payload["file"] = path.name
            items.append(payload)
        except Exception:
            logger.debug("Skipping unreadable suite summary %s", path, exc_info=True)
            continue
    return items


def _load_model_metadata(paths: WorkspacePaths) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for path in sorted(paths.models_dir.glob("*.json"), reverse=True):
        try:
            payload = JsonCache.read(path)
        except Exception:
            logger.debug("Skipping unreadable model metadata %s", path, exc_info=True)
            continue
        payload["name"] = path.name
        items.append(payload)
    return items


def _load_all_baselines_indexed(paths: WorkspacePaths) -> Dict[str, Dict[str, Any]]:
    """
    Load all baseline metadata once and index by name.

    This prevents N+1 lookups when processing runs. Delegates to
    BaselineManager so the directory-walk/JSON-read logic lives in one place
    instead of being duplicated here.

    Returns:
        Dict mapping baseline name to its details (same format as get_baseline_details).
    """
    return BaselineManager(paths).list_baselines_indexed()


def _load_runs(paths: WorkspacePaths, baselines_indexed: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Load all runs using the database runs_index table, falling back to folder scanning if database query fails.
    """
    from .database import get_store
    
    rows = []
    try:
        store = get_store(paths.db_path)
        rows = store._execute_query(
            "SELECT * FROM runs_index ORDER BY created_at DESC;",
            fetch=True
        )
    except Exception as e:
        logger.warning("[Dashboard Data] DB query failed; falling back to folder scan: %s", e)
        rows = []

    if rows:
        runs: List[Dict[str, Any]] = []
        for row in rows:
            run_id = row["run_id"]
            mismatch_pct = row.get("mismatch_pct") or 0.0
            status = row.get("status")
            decision_status = row.get("decision_status") or "pending"
            
            review_status = _normalize_review_status(
                status,
                decision_status,
                mismatch_pct=mismatch_pct,
            )
            ai_label = _sanitize_ai_label(row.get("ai_label"))
            baseline_name = row.get("baseline_name") or row.get("case_name")
            baseline_details = baselines_indexed.get(baseline_name) if baseline_name else None
            
            runs.append(
                {
                    "run": run_id,
                    "id": run_id,
                    "case_name": row.get("case_name"),
                    "name": row.get("case_name"),
                    "review_status": review_status,
                    "status": _normalize_run_status(status, decision_status),
                    "decision_status": decision_status,
                    "decider": row.get("decider") or "",
                    "decision_comment": row.get("decision_comment") or "",
                    "decided_at": row.get("decided_at") or "",
                    "mismatch_pct": mismatch_pct,
                    "mismatch": mismatch_pct,
                    "diff_regions": row.get("diff_regions") or 0,
                    "ai_label": ai_label,
                    "ignore_regions": [],
                    "ai_score": row.get("ai_score"),
                    "ai_explanation": "",
                    "severity": {"label": row.get("severity_label") or ""},
                    "locale": row.get("locale"),
                    "browser": row.get("browser"),
                    "device": row.get("device"),
                    "url": row.get("url"),
                    "baseline_name": baseline_name,
                    "baseline_image_href": baseline_details.get("current_image_href") if baseline_details else None,
                    "suite_name": row.get("suite_name"),
                    "build_id": row.get("build_id"),
                    "report_href": row.get("report_href") or f"/artifacts/{run_id}/report.html",
                }
            )
        return runs

    # ── Fallback: Load all runs from folder scanning ─────────────────────────
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
            logger.debug("Skipping unreadable run result %s", result_file, exc_info=True)
            continue

        result = payload.get("result", {})
        ai_assessment = payload.get("ai_assessment", {})
        decision = payload.get("decision") or payload.get("review", {})
        capture = payload.get("capture", {})
        severity = payload.get("severity", {})
        baseline_name = payload.get("baseline_name") or payload.get("case_name")
        threshold_pct = payload.get("threshold_pct")
        mismatch_pct = result.get("mismatch_pct")
        review_status = _normalize_review_status(
            payload.get("status"),
            decision.get("status"),
            mismatch_pct=mismatch_pct,
            threshold_pct=threshold_pct,
        )
        ai_label = _sanitize_ai_label(ai_assessment.get("label"))
        
        # Look up baseline from pre-loaded index (O(1) lookup, no file I/O)
        baseline_details = baselines_indexed.get(baseline_name) if baseline_name else None
        
        runs.append(
            {
                "run": run_dir.name,
                "id": run_dir.name,
                "case_name": payload.get("case_name"),
                "name": payload.get("case_name"),
                "review_status": review_status,
                "status": _normalize_run_status(payload.get("status"), decision.get("status")),
                "decision_status": decision.get("status") or "pending",
                "decider": decision.get("reviewer") or decision.get("decider"),
                "decision_comment": decision.get("comment"),
                "decided_at": decision.get("timestamp"),
                "mismatch_pct": result.get("mismatch_pct"),
                "mismatch": result.get("mismatch_pct"),
                "diff_regions": len(result.get("regions", [])),
                "ai_label": ai_label,
                "ignore_regions": payload.get("ignore_regions") or [],
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
                "build_id": payload.get("build_id"),
                "report_href": f"/artifacts/{run_dir.name}/report.html",
            }
        )
    return runs


def _load_builds(paths: WorkspacePaths, runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    builds: List[Dict[str, Any]] = []
    if not paths.builds_dir.exists():
        return builds
        
    # Group runs by build_id to optimize counting
    runs_by_build: Dict[str, List[Dict[str, Any]]] = {}
    for run in runs:
        b_id = run.get("build_id")
        if b_id:
            if b_id not in runs_by_build:
                runs_by_build[b_id] = []
            runs_by_build[b_id].append(run)

    for build_dir in sorted(paths.builds_dir.iterdir(), key=lambda p: p.name, reverse=True):
        if not build_dir.is_dir():
            continue
        meta_file = build_dir / "build.json"
        if not meta_file.exists():
            continue
        try:
            payload = json.loads(meta_file.read_text(encoding="utf-8"))
            b_id = payload.get("build_id")
            
            # Compute counts dynamically from runs if runs exist
            if b_id and b_id in runs_by_build:
                b_runs = runs_by_build[b_id]
                unreviewed_count = sum(1 for r in b_runs if r.get("review_status") == "unreviewed")
                rejected_count = sum(1 for r in b_runs if r.get("review_status") == "rejected")
                approved_count = sum(1 for r in b_runs if r.get("review_status") in ("approved", "no_changes"))
                
                payload["passed_count"] = approved_count
                payload["failed_count"] = unreviewed_count + rejected_count
                payload["total_count"] = len(b_runs)
                payload["status"] = "passed" if payload["failed_count"] == 0 else "failed"
                
            builds.append(payload)
        except Exception:
            logger.debug("Skipping unreadable build metadata %s", meta_file, exc_info=True)
            continue
    return builds


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
    builds = _load_builds(paths, runs)
    
    models = _load_model_metadata(paths)
    latest_suite = _latest_suite_summary(paths, runs)
    recent_summaries = _recent_suite_summaries(paths, runs)
    
    # Compute filter values from runs and baselines
    browser_values = {item.get("browser") for item in runs if item.get("browser")}
    browser_values.update(item.get("capture", {}).get("browser") for item in baselines if item.get("capture", {}).get("browser"))
    locale_values = {item.get("locale") for item in runs if item.get("locale")}
    locale_values.update(item.get("capture", {}).get("locale") for item in baselines if item.get("capture", {}).get("locale"))
    device_values = {item.get("device") or "desktop" for item in runs if item.get("browser")}
    device_values.update(item.get("capture", {}).get("device") or "desktop" for item in baselines if item.get("capture", {}).get("browser"))

    metrics = {
        "baseline_count": len(baselines),
        "run_count": len(runs),
        "build_count": len(builds),
        "failed_runs": sum(1 for item in runs if item.get("review_status") == "unreviewed"),
        "unreviewed_runs": sum(1 for item in runs if item.get("review_status") == "unreviewed"),
        "rejected_runs": sum(1 for item in runs if item.get("review_status") == "rejected"),
        "no_changes_runs": sum(1 for item in runs if item.get("review_status") == "no_changes"),
        "pending_decisions": sum(1 for item in runs if item.get("review_status") == "unreviewed"),
        "approved_decisions": sum(1 for item in runs if item.get("review_status") == "approved"),
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
        "builds": builds,
        "models": models,
        "latest_suite": latest_suite,
        "recent_summaries": recent_summaries,
    }
    
    # Cache result
    _DashboardCache.set(paths, snapshot)
    return snapshot
