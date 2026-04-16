from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .baseline_manager import BaselineManager
from .config import WorkspacePaths


def _latest_suite_summary(paths: WorkspacePaths) -> Dict[str, Any] | None:
    summaries = sorted(paths.reports_dir.glob("suite-summary-*.json"), reverse=True)
    for path in summaries:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return None


def _recent_suite_summaries(paths: WorkspacePaths, limit: int = 6) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for path in sorted(paths.reports_dir.glob("suite-summary-*.json"), reverse=True)[:limit]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        payload["file"] = path.name
        items.append(payload)
    return items


def _load_model_metadata(paths: WorkspacePaths) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for path in sorted(paths.models_dir.glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        payload["name"] = path.name
        items.append(payload)
    return items


def _load_runs(paths: WorkspacePaths) -> List[Dict[str, Any]]:
    baseline_manager = BaselineManager(paths)
    runs: List[Dict[str, Any]] = []
    for run_dir in sorted(paths.runs_dir.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        result_file = run_dir / "result.json"
        if not result_file.exists():
            continue
        try:
            payload = json.loads(result_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        result = payload.get("result", {})
        ai_assessment = payload.get("ai_assessment", {})
        decision = payload.get("decision") or payload.get("review", {})
        capture = payload.get("capture", {})
        severity = payload.get("severity", {})
        baseline_name = payload.get("baseline_name") or payload.get("case_name")
        baseline_details = None
        if baseline_name and baseline_manager.exists(str(baseline_name)):
            baseline_details = baseline_manager.get_baseline_details(str(baseline_name))
        runs.append(
            {
                "run": run_dir.name,
                "case_name": payload.get("case_name"),
                "status": payload.get("status"),
                "decision_status": decision.get("status"),
                "decider": decision.get("reviewer") or decision.get("decider"),
                "decision_comment": decision.get("comment"),
                "decided_at": decision.get("timestamp"),
                "mismatch_pct": result.get("mismatch_pct"),
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
    paths.ensure()
    baseline_manager = BaselineManager(paths)
    baselines = baseline_manager.list_baselines()
    runs = _load_runs(paths)
    models = _load_model_metadata(paths)
    latest_suite = _latest_suite_summary(paths)
    recent_summaries = _recent_suite_summaries(paths)
    browser_values = {item.get("browser") for item in runs if item.get("browser")}
    browser_values.update(item.get("browser") for item in baselines if item.get("browser"))
    locale_values = {item.get("locale") for item in runs if item.get("locale")}
    locale_values.update(item.get("locale") for item in baselines if item.get("locale"))
    device_values = {item.get("device") or "desktop" for item in runs if item.get("browser")}
    device_values.update(item.get("device") or "desktop" for item in baselines if item.get("browser"))

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

    return {
        "project_root": str(project_root),
        "metrics": metrics,
        "baselines": baselines,
        "runs": runs,
        "models": models,
        "latest_suite": latest_suite,
        "recent_summaries": recent_summaries,
    }
