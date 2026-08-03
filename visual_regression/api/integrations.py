"""Webhook configuration, the automation API key, and the GitHub OAuth flow.

Everything that returns or accepts a credential here is admin-only. The webhook
URL is included in that: a Slack/Discord/Teams webhook URL *is* its own bearer
credential — anyone holding it can post as the integration — so it gets the same
treatment as the API key rather than being handed to viewers and developers.
"""

from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse

from ..dashboard_data import _DashboardCache
from ..github_oauth import (
    build_authorize_url,
    exchange_code_for_token,
    fetch_github_user,
    oauth_settings,
)
from ..integrations_manager import IntegrationsManager
from .deps import (
    _API_KEY_CACHE,
    _API_KEY_LOCK,
    get_paths_dep,
    get_port_dep,
    get_project_root_dep,
    require_admin,
    require_auth,
)
from .urls import get_base_url, get_github_repo_url

router = APIRouter(tags=["integrations"])

_CALLBACK_PATH = "/api/integrations/github/callback"


def _oauth_settings_for(port: int):
    return oauth_settings(f"{get_base_url(port)}{_CALLBACK_PATH}")


def _redirect_with_error(message: str) -> RedirectResponse:
    return RedirectResponse(f"/integrations?github_error={quote_plus(message)}")


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

@router.get("/api/integrations")
def get_integrations(paths=Depends(get_paths_dep), port=Depends(get_port_dep), user=Depends(require_auth)):
    config = IntegrationsManager(paths.root).get_config()
    token = config.get("api_key", "")
    masked_token = (token[:7] + "*" * 20) if len(token) > 10 else "********"
    webhook_url = config.get("webhook_url", "")
    return {
        "webhook_url": webhook_url if user.role == "admin" else "",
        "webhook_threshold": config.get("webhook_threshold", 1.0),
        "api_key": masked_token,
        "webhook_connected": bool(webhook_url),
        "activity_count": len(config.get("activity", [])),
        "github_configured": _oauth_settings_for(port)["configured"],
    }


@router.get("/api/integrations/activity")
def get_integrations_activity(paths=Depends(get_paths_dep), user=Depends(require_auth)):
    config = IntegrationsManager(paths.root).get_config()
    return {"activity": config.get("activity", [])}


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

@router.post("/api/integrations/webhooks")
def post_integrations_webhooks(payload: dict, paths=Depends(get_paths_dep), user=Depends(require_admin)):
    url = str(payload.get("url", "")).strip()
    threshold = float(payload.get("threshold", 1.0))
    IntegrationsManager(paths.root).update_webhook(url, threshold)
    _DashboardCache.invalidate(paths)
    return {"ok": True}


@router.post("/api/integrations/test-webhook")
def post_integrations_test_webhook(payload: dict, paths=Depends(get_paths_dep), user=Depends(require_admin)):
    url = str(payload.get("url", "")).strip()
    if not url:
        raise HTTPException(status_code=400, detail="Webhook URL is required")
    from ..notifier import trigger_webhook_detailed

    result = trigger_webhook_detailed(url, {"event": "test_ping", "message": "The Lens Integration Test"})
    IntegrationsManager(paths.root).log_activity(
        message="Webhook test succeeded" if result.get("ok") else "Webhook test failed",
        branch="integrations",
        status="success" if result.get("ok") else "failed",
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail="Webhook test failed")
    return result


# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------

@router.post("/api/integrations/rotate-key")
def post_integrations_rotate_key(paths=Depends(get_paths_dep), user=Depends(require_admin)):
    new_key = IntegrationsManager(paths.root).rotate_api_key()
    # Drop the cached key immediately: otherwise the old one keeps authorising
    # requests for up to the cache TTL after it was supposedly revoked.
    with _API_KEY_LOCK:
        _API_KEY_CACHE.clear()
    return {"ok": True, "api_key": new_key}


@router.post("/api/integrations/reveal-key")
def post_integrations_reveal_key(paths=Depends(get_paths_dep), user=Depends(require_admin)):
    return {"ok": True, "api_key": IntegrationsManager(paths.root).reveal_api_key()}


# ---------------------------------------------------------------------------
# GitHub OAuth
# ---------------------------------------------------------------------------

@router.get("/api/integrations/github/status")
def get_github_status(
    paths=Depends(get_paths_dep),
    project_root=Depends(get_project_root_dep),
    port=Depends(get_port_dep),
):
    settings = _oauth_settings_for(port)
    return {
        "configured": settings["configured"],
        "redirect_uri": settings["redirect_uri"],
        "repo_url": get_github_repo_url(project_root),
        **IntegrationsManager(paths.root).github_status(),
    }


@router.post("/api/integrations/github/connect")
def post_integrations_github_connect(
    paths=Depends(get_paths_dep), port=Depends(get_port_dep), user=Depends(require_admin)
):
    settings = _oauth_settings_for(port)
    if not settings["configured"]:
        raise HTTPException(
            status_code=400,
            detail=(
                "GitHub OAuth is not configured. Set GITHUB_OAUTH_CLIENT_ID and "
                "GITHUB_OAUTH_CLIENT_SECRET on the dashboard server."
            ),
        )
    state = IntegrationsManager(paths.root).begin_github_oauth()
    return {
        "ok": True,
        "authorize_url": build_authorize_url(
            client_id=settings["client_id"],
            redirect_uri=settings["redirect_uri"],
            state=state,
            scope=settings["scope"],
        ),
    }


@router.get(_CALLBACK_PATH)
def get_github_callback(
    code: str = None,
    state: str = None,
    error: str = None,
    error_description: str = None,
    paths=Depends(get_paths_dep),
    project_root=Depends(get_project_root_dep),
    port=Depends(get_port_dep),
):
    manager = IntegrationsManager(paths.root)

    if error:
        err_val = error_description or error or "Authorization failed"
        manager.log_activity(f"GitHub OAuth failed: {err_val}", branch="integrations", status="failed")
        return _redirect_with_error(err_val)

    if not code or not state:
        return _redirect_with_error("Missing code or state")

    # The state is the CSRF defence on this callback: without it, anyone could
    # send a victim here with an attacker's code and bind the attacker's GitHub
    # account to this instance.
    if not manager.validate_github_state(state):
        manager.log_activity("GitHub OAuth failed: invalid state", branch="integrations", status="failed")
        return _redirect_with_error("Invalid or expired state")

    settings = _oauth_settings_for(port)
    if not settings["configured"]:
        return _redirect_with_error("GitHub OAuth is not configured")

    token_payload = exchange_code_for_token(
        client_id=settings["client_id"],
        client_secret=settings["client_secret"],
        code=code,
        redirect_uri=settings["redirect_uri"],
    )
    if "error" in token_payload:
        err_val = (
            token_payload.get("error_description")
            or token_payload.get("error")
            or "Unable to exchange OAuth code"
        )
        manager.log_activity(f"GitHub OAuth failed: {err_val}", branch="integrations", status="failed")
        return _redirect_with_error(err_val)

    access_token = token_payload.get("access_token", "")
    if not access_token:
        return _redirect_with_error("Missing access token")
    scopes = [scope for scope in str(token_payload.get("scope", "")).split(",") if scope]

    manager.complete_github_oauth(
        access_token=access_token, user=fetch_github_user(access_token), scopes=scopes
    )
    return RedirectResponse("/integrations?github=connected")


@router.post("/api/integrations/github/disconnect")
def post_integrations_github_disconnect(paths=Depends(get_paths_dep), user=Depends(require_admin)):
    IntegrationsManager(paths.root).disconnect_github()
    return {"ok": True}
