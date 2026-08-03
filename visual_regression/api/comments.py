"""Review comments pinned to a point on a run's screenshot."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from .deps import get_current_user, get_store_dep, require_auth, require_authorized_client
from .events import broadcast_event

router = APIRouter(tags=["comments"])


@router.get("/api/comments")
def get_comments(run_id: str = Query(None), store=Depends(get_store_dep), user=Depends(require_auth)):
    if not run_id:
        raise HTTPException(status_code=400, detail="Missing run_id parameter")
    return {"ok": True, "comments": store.list_comments(run_id)}


@router.post("/api/comments/create")
def post_comments_create(
    payload: dict,
    store=Depends(get_store_dep),
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
    broadcast_event("comment_updated", {"run_id": run_id, "action": "create", "comment_id": comment_id})
    return {"ok": True, "comment_id": comment_id}


@router.post("/api/comments/delete")
def post_comments_delete(
    payload: dict,
    store=Depends(get_store_dep),
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
    broadcast_event(
        "comment_updated",
        {"run_id": comment["run_id"], "action": "delete", "comment_id": comment_id},
    )
    return {"ok": True}
