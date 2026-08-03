"""Shared FastAPI dependencies: request state accessors and authorisation.

These live here rather than in dashboard_server so the routers can import them
without importing the app module back (which would be a cycle).

State is read off ``request.app.state`` rather than a module-level ``app``
object. That is what makes the split possible at all, and it is also more
correct: a dependency that closes over one specific app instance cannot be
reused by a second one, which is exactly what a test that builds its own app
needs to do. ``request.state`` still takes precedence so a middleware or a test
can override per request.
"""

from __future__ import annotations

import hmac
import threading
import time
from typing import Any, Dict

from fastapi import Depends, HTTPException, Request

from ..integrations_manager import IntegrationsManager

# The automation access key is read from integrations.json on every request that
# presents one. Cache it briefly so a burst of CI uploads does not re-read and
# re-decrypt the file each time.
_API_KEY_CACHE: Dict[str, Any] = {}
_API_KEY_TTL = 60.0
_API_KEY_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Request state
# ---------------------------------------------------------------------------

def get_paths_dep(request: Request):
    if hasattr(request.state, "paths"):
        return request.state.paths
    return getattr(request.app.state, "paths", None)


def get_store_dep(request: Request):
    if hasattr(request.state, "store"):
        return request.state.store
    return getattr(request.app.state, "store", None)


def get_project_root_dep(request: Request):
    if hasattr(request.state, "project_root"):
        return request.state.project_root
    return getattr(request.app.state, "project_root", None)


def get_port_dep(request: Request):
    if hasattr(request.state, "port"):
        return request.state.port
    return getattr(request.app.state, "port", None)


# ---------------------------------------------------------------------------
# Access key
# ---------------------------------------------------------------------------

def _resolve_access_key(paths) -> str:
    """Return the configured automation key, caching it for _API_KEY_TTL."""
    now = time.time()
    with _API_KEY_LOCK:
        if _API_KEY_CACHE.get("expires_at", 0) > now:
            return _API_KEY_CACHE["value"]
        secure_key = IntegrationsManager(paths.root).get_config().get("api_key", "")
        _API_KEY_CACHE["value"] = secure_key
        _API_KEY_CACHE["expires_at"] = now + _API_KEY_TTL
        return secure_key


def _access_key_matches(request: Request, paths) -> bool:
    """Constant-time comparison of the X-Access-Key header against the config.

    An empty configured key never matches, so a workspace with no key set stays
    closed rather than accepting an empty header.
    """
    incoming = request.headers.get("X-Access-Key") or ""
    if not incoming:
        return False
    secure_key = _resolve_access_key(paths)
    return bool(secure_key) and hmac.compare_digest(incoming, secure_key)


# ---------------------------------------------------------------------------
# Authorisation
# ---------------------------------------------------------------------------

def get_current_user(request: Request, store=Depends(get_store_dep)):
    token = request.cookies.get("lens_session")
    if not token:
        return None
    return store.user_for_session(token)


def require_auth(user=Depends(get_current_user)):
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def require_admin(user=Depends(require_auth)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Forbidden")
    return user


def require_dev_or_admin(
    request: Request,
    user=Depends(get_current_user),
    paths=Depends(get_paths_dep),
):
    if _access_key_matches(request, paths):
        return True
    if user and user.role in ("admin", "developer"):
        return user
    raise HTTPException(status_code=403, detail="Forbidden")


def check_authorization(
    request: Request,
    user=Depends(get_current_user),
    paths=Depends(get_paths_dep),
):
    # Any authenticated session user (admin/developer/viewer) can view images —
    # they can already see the run/baseline metadata that links to them via
    # require_auth, which doesn't gate by role either.
    if user:
        return True
    return _access_key_matches(request, paths)


def require_authorized_client(request: Request, is_auth=Depends(check_authorization)):
    if not is_auth:
        raise HTTPException(status_code=403, detail="Forbidden")
    return True
