"""Scheduled-suite CRUD.

The scheduler instance is read off ``request.app.state`` rather than imported.
A module-level ``_GLOBAL_SCHEDULER`` would be bound at import time — when it is
still None — so a router importing the name would see None forever no matter
what startup assigned afterwards.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from .deps import get_project_root_dep, require_auth, require_dev_or_admin
from .events import broadcast_event

router = APIRouter(tags=["scheduler"])


def _get_scheduler(request: Request):
    scheduler = getattr(request.app.state, "scheduler", None)
    if not scheduler:
        raise HTTPException(status_code=500, detail="Scheduler not initialized")
    return scheduler


def _safe_relative_suite_path(project_root: Path, suite_path: str) -> str:
    """Resolve a caller-supplied suite path, refusing anything outside the project.

    The stored value is relative to project_root because the scheduler runs its
    jobs in a subprocess with project_root as the working directory.
    """
    suite_path = str(suite_path).strip()
    if not suite_path.lower().endswith((".yaml", ".yml")):
        raise HTTPException(status_code=400, detail="suite_path must be a .yaml/.yml file")

    root = project_root.resolve()
    resolved = (root / suite_path).resolve()
    if root != resolved and root not in resolved.parents:
        raise HTTPException(status_code=400, detail="suite_path must be inside the project")
    if not resolved.is_file():
        raise HTTPException(status_code=400, detail=f"Suite file not found: {suite_path}")
    return str(resolved.relative_to(root))


@router.get("/api/scheduler/jobs")
def get_scheduler_jobs(request: Request, user=Depends(require_auth)):
    scheduler = getattr(request.app.state, "scheduler", None)
    if not scheduler:
        return {"ok": False, "jobs": []}
    return {"ok": True, "jobs": [asdict(j) for j in scheduler.list_jobs()]}


@router.post("/api/scheduler/jobs")
def post_scheduler_jobs(
    payload: dict,
    request: Request,
    project_root=Depends(get_project_root_dep),
    user=Depends(require_dev_or_admin),
):
    name = payload.get("name")
    cron_expression = payload.get("cron_expression")
    suite_path = payload.get("suite_path")
    if not name or not cron_expression or not suite_path:
        raise HTTPException(status_code=400, detail="Missing required fields")

    scheduler = _get_scheduler(request)
    safe_suite_path = _safe_relative_suite_path(project_root, suite_path)

    job_id = scheduler.add_job(name, cron_expression, safe_suite_path)
    broadcast_event("scheduler_updated", {"action": "add", "job_id": job_id})
    return {"ok": True, "job_id": job_id}


@router.post("/api/scheduler/jobs/delete")
def post_scheduler_jobs_delete(payload: dict, request: Request, user=Depends(require_dev_or_admin)):
    job_id = payload.get("job_id")
    if not job_id:
        raise HTTPException(status_code=400, detail="Missing job_id")
    success = _get_scheduler(request).remove_job(job_id)
    broadcast_event("scheduler_updated", {"action": "delete", "job_id": job_id})
    return {"ok": success}


@router.post("/api/scheduler/jobs/toggle")
def post_scheduler_jobs_toggle(payload: dict, request: Request, user=Depends(require_dev_or_admin)):
    job_id = payload.get("job_id")
    enabled = bool(payload.get("enabled", True))
    if not job_id:
        raise HTTPException(status_code=400, detail="Missing job_id")
    success = _get_scheduler(request).enable_job(job_id, enabled)
    broadcast_event("scheduler_updated", {"action": "toggle", "job_id": job_id, "enabled": enabled})
    return {"ok": success}
