"""User management. Every route here is admin-only.

The recurring concern in this module is lockout: require_admin gates all of it,
so any operation that could remove the last admin leaves nobody able to
administer the instance and no way back in through the UI. Delete, demote and
disable all have to guard that, not just delete.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .deps import get_store_dep, require_admin

router = APIRouter(tags=["users"])


def _is_last_admin(store, email: str) -> bool:
    all_users = store.list_users()
    target = next((u for u in all_users if u.get("email", "").lower() == email.lower()), None)
    if not target or target.get("role") != "admin":
        return False
    return sum(1 for u in all_users if u.get("role") == "admin") <= 1


@router.get("/api/users")
def get_users(store=Depends(get_store_dep), user=Depends(require_admin)):
    return {"ok": True, "users": store.list_users()}


@router.post("/api/users")
def post_users(payload: dict, store=Depends(get_store_dep), user=Depends(require_admin)):
    email = str(payload.get("email", "")).strip()
    password = str(payload.get("password", ""))
    role = str(payload.get("role", "viewer")).strip()
    name = str(payload.get("name", "")).strip()
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required")
    try:
        store.create_user(email, password, role=role, display_name=name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=409, detail="User already exists")
    store.audit(user.email, user.role, "users.create", {"email": email, "role": role})
    return {"ok": True}


@router.post("/api/users/delete")
def post_users_delete(payload: dict, store=Depends(get_store_dep), user=Depends(require_admin)):
    email = str(payload.get("email", "")).strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    if user.email == email.lower():
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    if _is_last_admin(store, email):
        raise HTTPException(status_code=400, detail="Cannot delete the last admin account")
    store.delete_user(email)
    store.audit(user.email, user.role, "users.delete", {"email": email})
    return {"ok": True}


@router.post("/api/users/update")
def post_users_update(payload: dict, store=Depends(get_store_dep), user=Depends(require_admin)):
    email = str(payload.get("email", "")).strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    role = payload.get("role")
    disabled = payload.get("disabled")
    password = payload.get("password")
    display_name = payload.get("display_name")
    if role is not None:
        role = str(role).strip()
    if password is not None:
        password = str(password) or None
    if display_name is not None:
        display_name = str(display_name).strip()

    # Demoting or disabling the last admin is just as much a lockout as
    # deleting them, so it is guarded the same way.
    would_lose_admin = (role and role != "admin") or disabled is True
    if would_lose_admin and _is_last_admin(store, email):
        raise HTTPException(
            status_code=400, detail="Cannot demote or disable the last admin account"
        )

    try:
        store.update_user(
            email,
            role=role if role else None,
            disabled=bool(disabled) if disabled is not None else None,
            password=password,
            display_name=display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    store.audit(user.email, user.role, "users.update", {"email": email})
    return {"ok": True}
