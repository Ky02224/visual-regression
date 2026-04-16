from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
import shutil

from .config import WorkspacePaths
from .reporter import render_html_report_from_payload, write_json
from .baseline_manager import BaselineManager


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReviewManager:
    def __init__(self, paths: WorkspacePaths):
        self.paths = paths
        self.paths.ensure()

    def resolve_run_dir(self, run_ref: str) -> Path:
        candidate = Path(run_ref)
        if candidate.exists() and candidate.is_dir():
            return candidate
        run_dir = self.paths.runs_dir / run_ref
        if run_dir.exists() and run_dir.is_dir():
            return run_dir
        raise FileNotFoundError(f"Run '{run_ref}' not found")

    def list_runs(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for run_dir in sorted(self.paths.runs_dir.iterdir(), reverse=True):
            if not run_dir.is_dir():
                continue
            result_file = run_dir / "result.json"
            if not result_file.exists():
                continue
            payload = self.load_run_payload(run_dir)
            items.append(
                {
                    "run": run_dir.name,
                    "case_name": payload.get("case_name"),
                    "status": payload.get("status"),
                    "decision_status": (payload.get("decision") or payload.get("review", {})).get("status"),
                    "report": payload.get("artifacts", {}).get("report"),
                }
            )
        return items

    @staticmethod
    def load_run_payload(run_dir: Path) -> Dict[str, Any]:
        result_file = run_dir / "result.json"
        if not result_file.exists():
            raise FileNotFoundError(f"Missing result.json in {run_dir}")
        import json

        return json.loads(result_file.read_text(encoding="utf-8"))

    def save_decision(
        self,
        run_dir: Path,
        decision: str,
        decider: str,
        comment: str | None,
    ) -> Dict[str, Any]:
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")

        payload = self.load_run_payload(run_dir)
        decision_record = {
            "status": decision,
            "decider": decider,
            "comment": comment or "",
            "timestamp": _utc_now(),
        }
        history = list(payload.get("decision_history") or [])
        latest_existing = payload.get("decision") or payload.get("review")
        if latest_existing and not history:
            history.append(latest_existing)
        history.append(decision_record)
        payload["decision"] = decision_record
        payload["decision_history"] = history[-25:]

        # CRITICAL BUG FIX: If approved, promote the current image to be the new baseline
        if decision == "approved":
            case_name = payload.get("case_name") or payload.get("baseline_name")
            if case_name:
                current_image = run_dir / "current.png"
                if current_image.exists():
                    bm = BaselineManager(self.paths)
                    # Use existing capture meta but update the actor
                    capture_meta = dict(payload.get("capture", {}))
                    capture_meta["updated_by"] = decider
                    capture_meta["source"] = "manual_approval"
                    bm.save_from_image(case_name, current_image, capture_meta)

        payload.pop("review", None)
        payload.pop("review_history", None)
        write_json(run_dir / "result.json", payload)
        render_html_report_from_payload(run_dir / "report.html", payload)
        return decision_record

    # Backward-compatible alias for older call sites.
    def save_review(
        self,
        run_dir: Path,
        decision: str,
        reviewer: str,
        comment: str | None,
    ) -> Dict[str, Any]:
        return self.save_decision(run_dir=run_dir, decision=decision, decider=reviewer, comment=comment)

    def delete_run(self, run_ref: str) -> Dict[str, Any]:
        run_dir = self.resolve_run_dir(run_ref).resolve()
        runs_root = self.paths.runs_dir.resolve()
        if runs_root not in run_dir.parents:
            raise ValueError("Refusing to delete a run outside the runs directory")
        if not run_dir.exists():
            raise FileNotFoundError(f"Run '{run_ref}' not found")
        shutil.rmtree(run_dir)
        return {"run": run_dir.name, "deleted": True}
