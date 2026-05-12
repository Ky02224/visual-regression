from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any, Dict


def oauth_settings(default_redirect_uri: str) -> Dict[str, Any]:
    client_id = os.environ.get("GITHUB_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", "").strip()
    redirect_uri = os.environ.get("GITHUB_OAUTH_REDIRECT_URI", "").strip() or default_redirect_uri
    return {
        "configured": bool(client_id and client_secret),
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "scope": "read:user",
    }


def build_authorize_url(client_id: str, redirect_uri: str, state: str, scope: str = "read:user") -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
            "allow_signup": "true",
            "prompt": "select_account",
        }
    )
    return f"https://github.com/login/oauth/authorize?{query}"


def exchange_code_for_token(client_id: str, client_secret: str, code: str, redirect_uri: str) -> Dict[str, Any]:
    payload = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://github.com/login/oauth/access_token",
        data=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "visual-regression-dashboard",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_github_user(access_token: str) -> Dict[str, Any]:
    request = urllib.request.Request(
        "https://api.github.com/user",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "visual-regression-dashboard",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))
