from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import shutil

from .config import WorkspacePaths, resolve_image_path
from .reporter import render_html_report_from_payload, write_json
from .baseline_manager import BaselineManager
from ._json_cache import JsonCache
from ._file_lock import FileLock, atomic_replace

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReviewManager:
    def __init__(self, paths: WorkspacePaths):
        self.paths = paths
        self.paths.ensure()

    def resolve_run_dir(self, run_ref: str) -> Path:
        # Confine to runs_dir — run_ref comes straight from request payloads
        # (bulk review, single review, delete), so an absolute path or a
        # "../" traversal must not be able to resolve to an arbitrary
        # directory on disk. Previously only delete_run checked this
        # (after the fact); save_decision and friends did not.
        runs_root = self.paths.runs_dir.resolve()
        run_dir = (self.paths.runs_dir / run_ref).resolve()
        if runs_root in run_dir.parents and run_dir.exists() and run_dir.is_dir():
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
        return JsonCache.read(result_file)

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
                current_image = resolve_image_path(run_dir, "current")
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

        # Persist this decision for active learning data collection.
        try:
            compare_result_dict = dict(payload.get("result") or {})
            diff_image_path: Optional[Path] = None
            for candidate_base in ("diff_overlay", "binary_diff"):
                candidate_path = resolve_image_path(run_dir, candidate_base)
                if candidate_path.exists():
                    diff_image_path = candidate_path
                    break
            record_review_for_active_learning(
                run_id=run_dir.name,
                name=str(payload.get("case_name") or payload.get("baseline_name") or ""),
                decision=decision,
                compare_result_dict=compare_result_dict,
                paths=self.paths,
                diff_image_path=diff_image_path,
            )
        except Exception as _al_exc:
            logger.warning(
                "[record_review_for_active_learning] Failed for run %s: %s",
                run_dir.name,
                _al_exc,
            )

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


def record_review_for_active_learning(
    run_id: str,
    name: str,
    decision: str,
    compare_result_dict: Dict[str, Any],
    paths: WorkspacePaths,
    diff_image_path: Optional[Path] = None,
) -> Path:
    """Persist a human review decision to the active-learning data store.

    Creates (if necessary) the directory ``<workspace>/.visual-regression/active_learning/``
    and writes a JSON record containing the run metadata, human decision, and
    comparison result.  If a diff / overlay image is provided it is also copied
    to ``active_learning/images/`` so that future model retraining can use it
    directly as a labelled training example.

    Args:
        run_id: Unique identifier for the run (usually the run directory name).
        name: Human-readable name / case name for the test.
        decision: Either ``"approved"`` or ``"rejected"``.
        compare_result_dict: Serialised :class:`~visual_regression.models.CompareResult`
            as a plain dict (already JSON-serialisable).
        paths: The :class:`~visual_regression.config.WorkspacePaths` instance for
            the current workspace.
        diff_image_path: Optional path to the diff or overlay image file.  When
            provided, the file is copied into the ``active_learning/images/``
            sub-directory alongside the JSON record.

    Returns:
        The :class:`pathlib.Path` of the saved JSON record.

    Example::

        saved = record_review_for_active_learning(
            run_id="run-20260707-001",
            name="homepage-desktop",
            decision="rejected",
            compare_result_dict=result.to_dict(),
            paths=workspace_paths,
            diff_image_path=Path(".visual-regression/runs/run-20260707-001/diff.png"),
        )
        print(f"Active learning record saved to: {saved}")
    """
    al_dir = paths.root / "active_learning"
    images_dir = al_dir / "images"
    al_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).isoformat()

    # Sanitise run_id for use as a filename component
    safe_run_id = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in run_id)
    record_filename = f"{safe_run_id}.json"
    record_path = al_dir / record_filename

    # Copy diff image if it exists
    copied_image_name: Optional[str] = None
    if diff_image_path is not None and diff_image_path.exists():
        dest_image = images_dir / f"{safe_run_id}_{diff_image_path.name}"
        try:
            shutil.copy2(str(diff_image_path), str(dest_image))
            copied_image_name = dest_image.name
            logger.debug(
                "[active_learning] Copied diff image %s -> %s",
                diff_image_path.name,
                dest_image.name,
            )
        except OSError as exc:
            logger.warning(
                "[active_learning] Could not copy diff image %s: %s",
                diff_image_path,
                exc,
            )

    record: Dict[str, Any] = {
        "run_id": run_id,
        "name": name,
        "decision": decision,
        "timestamp": timestamp,
        "compare_result": compare_result_dict,
        "diff_image": copied_image_name,
    }

    lock_path = al_dir / ".lock"
    try:
        with FileLock(lock_path, timeout=10.0):
            with tempfile.NamedTemporaryFile(
                "w",
                dir=al_dir,
                delete=False,
                suffix=".tmp",
                encoding="utf-8",
            ) as tmp:
                tmp.write(json.dumps(record, indent=2))
                tmp_path = Path(tmp.name)
            atomic_replace(tmp_path, record_path)
        logger.info(
            "[active_learning] Saved record for run %s (decision=%s) -> %s",
            run_id,
            decision,
            record_path.name,
        )
    except OSError as exc:
        logger.error(
            "[active_learning] Failed to write record for run %s: %s",
            run_id,
            exc,
        )
        raise

    return record_path
