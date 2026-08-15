"""Review comments pinned to a point on a run's screenshot."""

from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from .deps import (
    get_current_user,
    get_paths_dep,
    get_port_dep,
    get_store_dep,
    require_auth,
    require_authorized_client,
)
from .events import broadcast_event

logger = logging.getLogger(__name__)

router = APIRouter(tags=["comments"])


def _invalidate_dashboard(paths) -> None:
    """Drop the cached dashboard snapshot so the comment badge is not stale.

    The snapshot carries each run's comment count and is cached for 60s.
    """
    try:
        from ..dashboard_data import _DashboardCache

        _DashboardCache.invalidate(paths)
    except Exception as exc:
        logger.warning("Could not invalidate dashboard cache after comment change: %s", exc)


def _case_name_for(store, paths, run_id: str) -> str:
    """The run's human name, for a notification that has to read well.

    The index first because it survives a pruned run directory; result.json
    second because a run captured before the index existed still has one.
    """
    try:
        row = store.get_run_index(run_id) if store else None
        if row and (row.get("case_name") or row.get("baseline_name")):
            return str(row.get("case_name") or row.get("baseline_name"))
    except Exception as exc:
        logger.debug("Run index lookup failed for %s: %s", run_id, exc)
    try:
        from ..review_manager import ReviewManager

        manager = ReviewManager(paths)
        payload = manager.load_run_payload(manager.resolve_run_dir(run_id))
        name = payload.get("case_name") or payload.get("baseline_name")
        if name:
            return str(name)
    except Exception as exc:
        logger.debug("Run payload lookup failed for %s: %s", run_id, exc)
    return run_id


def _notify_comment(store, paths, port, run_id: str, author: str, content: str) -> None:
    """Best-effort webhook for a new comment.

    A pinned comment is usually a question for someone else, and it used to be
    visible only inside that one run's report. Sent through the same webhook
    the run notifications use, so it is off unless a webhook is configured.
    """
    try:
        from ..integrations_manager import IntegrationsManager
        from ..notifier import format_comment_added_payload, trigger_webhook_detailed

        manager = IntegrationsManager(paths.root)
        webhook_url = manager.get_config().get("webhook_url")
        if not webhook_url:
            return

        case_name = _case_name_for(store, paths, run_id)
        dashboard_url = os.environ.get("DASHBOARD_URL") or f"http://127.0.0.1:{port}"
        result = trigger_webhook_detailed(
            webhook_url,
            format_comment_added_payload(
                run_id=run_id,
                case_name=case_name,
                author=author,
                content=content,
                dashboard_url=dashboard_url,
            ),
        )
        manager.log_activity(
            message="Comment webhook sent" if result.get("ok") else "Comment webhook failed",
            branch="integrations",
            status="success" if result.get("ok") else "failed",
        )
    except Exception as exc:
        # Never fail the comment the reviewer just wrote because a webhook is
        # unreachable.
        logger.warning("Comment webhook failed for run %s: %s", run_id, exc)


@router.get("/api/comments")
def get_comments(run_id: str = Query(None), store=Depends(get_store_dep), user=Depends(require_auth)):
    if not run_id:
        raise HTTPException(status_code=400, detail="Missing run_id parameter")
    return {"ok": True, "comments": store.list_comments(run_id)}


@router.post("/api/comments/create")
def post_comments_create(
    payload: dict,
    store=Depends(get_store_dep),
    paths=Depends(get_paths_dep),
    port=Depends(get_port_dep),
    user=Depends(get_current_user),
    authorized=Depends(require_authorized_client),
):
    run_id = str(payload.get("run_id", "")).strip()
    content = str(payload.get("content", "")).strip()
    if not run_id or not content:
        raise HTTPException(status_code=400, detail="run_id and content are required")

    x_pct = float(payload.get("x_pct", 0.0))
    y_pct = float(payload.get("y_pct", 0.0))
    author = user.email if user else ("automation-api" if authorized else "anonymous")
    comment_id = f"comment-{uuid.uuid4()}"

    store.add_comment(comment_id, run_id, x_pct, y_pct, author, content)
    _invalidate_dashboard(paths)
    broadcast_event("comment_updated", {"run_id": run_id, "action": "create", "comment_id": comment_id})
    _notify_comment(store, paths, port, run_id, author, content)
    return {"ok": True, "comment_id": comment_id}


@router.post("/api/comments/delete")
def post_comments_delete(
    payload: dict,
    store=Depends(get_store_dep),
    paths=Depends(get_paths_dep),
    user=Depends(get_current_user),
    authorized=Depends(require_authorized_client),
):
    comment_id = str(payload.get("comment_id", "")).strip()
    if not comment_id:
        raise HTTPException(status_code=400, detail="comment_id is required")

    # One store call. This route used to issue two raw SQL queries against the
    # comments table — one for the author, one for the run_id — each with its
    # own sqlite/postgres branch, inside the HTTP handler.
    comment = store.get_comment(comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    is_admin = bool(user and user.role == "admin")
    is_author = bool(user and user.email == comment["author"])
    if not is_admin and not is_author and not authorized:
        raise HTTPException(status_code=403, detail="Forbidden")

    store.delete_comment(comment_id)
    _invalidate_dashboard(paths)
    broadcast_event(
        "comment_updated",
        {"run_id": comment["run_id"], "action": "delete", "comment_id": comment_id},
    )
    return {"ok": True}
