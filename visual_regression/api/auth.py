"""Session login/logout and the current-user probe."""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .deps import get_current_user, get_store_dep

router = APIRouter(tags=["auth"])

# In-memory per-IP login throttle. Deliberately not shared with the rest of the
# process: it protects the password check specifically, and losing it on restart
# is acceptable — an attacker who can restart the server has already won.
_LOGIN_LIMITER: Dict[str, List[float]] = defaultdict(list)
_LOGIN_LIMITER_LOCK = threading.Lock()
_MAX_LOGIN_ATTEMPTS_PER_MINUTE = 10

_SESSION_TTL_SECONDS = 60 * 60 * 12


def _secure_cookies() -> bool:
    return os.environ.get("LENS_SECURE_COOKIES") == "true"


@router.get("/api/auth/me")
def get_auth_me(user=Depends(get_current_user)):
    if not user:
        return {"ok": True, "authenticated": False, "user": None}
    return {
        "ok": True,
        "authenticated": True,
        "user": {"email": user.email, "role": user.role, "name": user.display_name},
    }


@router.post("/api/auth/login")
def post_auth_login(payload: dict, request: Request, response: Response, store=Depends(get_store_dep)):
    email = str(payload.get("email", "")).strip()
    password = str(payload.get("password", ""))
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password are required")

    client_ip = request.client.host if request.client else "127.0.0.1"
    now_ts = time.time()
    window_start_ts = now_ts - 60.0
    with _LOGIN_LIMITER_LOCK:
        recent = [t for t in _LOGIN_LIMITER[client_ip] if t > window_start_ts]
        if len(recent) >= _MAX_LOGIN_ATTEMPTS_PER_MINUTE:
            raise HTTPException(
                status_code=429,
                detail="Too many login attempts. Please wait a minute before trying again.",
            )
        recent.append(now_ts)
        _LOGIN_LIMITER[client_ip] = recent

    user = store.authenticate(email, password)
    if not user:
        store.audit(None, None, "auth.login_failed", {"email": email})
        raise HTTPException(status_code=401, detail="Invalid credentials")

    with _LOGIN_LIMITER_LOCK:
        _LOGIN_LIMITER.pop(client_ip, None)

    # Rotate the session on login so a token captured before authentication
    # cannot be reused afterwards.
    old_token = request.cookies.get("lens_session")
    if old_token:
        store.delete_session(old_token)
    token = store.create_session(user.email, ttl_seconds=_SESSION_TTL_SECONDS)
    response.set_cookie(
        key="lens_session",
        value=token,
        path="/",
        httponly=True,
        samesite="lax",
        max_age=_SESSION_TTL_SECONDS,
        secure=_secure_cookies(),
    )
    store.audit(user.email, user.role, "auth.login", {"email": user.email})
    return {"ok": True, "user": {"email": user.email, "role": user.role}}


@router.post("/api/auth/logout")
def post_auth_logout(request: Request, response: Response, store=Depends(get_store_dep)):
    token = request.cookies.get("lens_session")
    if token:
        user = store.user_for_session(token)
        if user:
            store.audit(user.email, user.role, "auth.logout", {"email": user.email})
        store.delete_session(token)
    response.delete_cookie(
        key="lens_session",
        path="/",
        httponly=True,
        samesite="lax",
        secure=_secure_cookies(),
    )
    return {"ok": True}
