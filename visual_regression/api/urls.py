"""Resolution of the dashboard's own public URL and the project's GitHub remote.

Both are process-wide caches rather than per-request lookups: the base URL is
fixed once at startup, and the git remote requires a subprocess, which is far
too expensive to repeat on every request that wants to build a link.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict

# Set by dashboard_server at startup. Behind a reverse proxy the loopback
# fallback is wrong in every link the dashboard emits — including the ones sent
# to Slack and to GitHub commit statuses — so the real external URL is recorded
# there and preferred here.
_STARTUP_BASE_URL: Dict[str, Any] = {}
_GITHUB_REPO_URL_CACHE: Dict[str, Any] = {}


def set_startup_base_url(url: str) -> None:
    _STARTUP_BASE_URL["value"] = url


def get_base_url(port: int) -> str:
    fixed = _STARTUP_BASE_URL.get("value")
    if fixed:
        return fixed
    return f"http://127.0.0.1:{port}"


def get_github_repo_url(project_root: Path) -> str:
    """Return the origin remote URL, or "" when there is no git repo or remote.

    The empty string is cached too — a project without a remote would otherwise
    spawn a git subprocess on every single request that asks.
    """
    cached = _GITHUB_REPO_URL_CACHE.get("value")
    if cached is not None:
        return cached
    try:
        process = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
        )
        result = process.stdout.strip() if process.returncode == 0 else ""
        _GITHUB_REPO_URL_CACHE["value"] = result
        return result
    except Exception:
        return ""
