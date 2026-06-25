from __future__ import annotations

import hmac
import json
import mimetypes
import subprocess
import sys
import time
import uuid
import io
from contextlib import redirect_stdout, redirect_stderr
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import parse_qs, quote_plus, urlparse

_task_executor = ThreadPoolExecutor(max_workers=4)
_tasks_status: Dict[str, Dict[str, Any]] = {}
_MAX_TASK_HISTORY = 500  # cap to prevent unbounded memory growth

from collections import defaultdict
_SDK_LIMITER: Dict[str, list[float]] = defaultdict(list)
_SDK_LIMITER_LOCK = None  # initialised after threading import below
_MAX_SNAPSHOTS_PER_MINUTE = 30

# Login brute-force rate limiter: ip -> list of attempt timestamps
_LOGIN_LIMITER: Dict[str, list[float]] = defaultdict(list)
_LOGIN_LIMITER_LOCK = None  # initialised after threading import below
_MAX_LOGIN_ATTEMPTS_PER_MINUTE = 10

# --------------------------------------------------------------------------- #
# API Key TTL cache — avoids reading integrations.json on every request.
# Invalidated explicitly when the key is rotated or integrations are updated.
# --------------------------------------------------------------------------- #
_API_KEY_CACHE: Dict[str, Any] = {}   # keys: "value", "expires_at"
_API_KEY_TTL = 60.0  # seconds
_API_KEY_LOCK = None  # initialised lazily after threading is imported

import threading

_ai_review_queue_lock = threading.Lock()
_API_KEY_LOCK = threading.Lock()   # for the API key TTL cache
_SDK_LIMITER_LOCK = threading.Lock()   # for the SDK snapshot rate limiter
_LOGIN_LIMITER_LOCK = threading.Lock()  # for the login brute-force limiter
_ai_review_queue_count = 0
_ai_training_in_progress = False
_last_ai_train_time = 0.0

_GLOBAL_PLAYWRIGHT = None
_GLOBAL_BROWSER = None
_GLOBAL_BROWSER_LOCK = threading.Lock()

# Cache for git remote origin URL — populated once at server startup (RISK-02 fix).
_GITHUB_REPO_URL_CACHE: Dict[str, Any] = {}

# Base URL fixed at startup to prevent Host-header injection on OAuth redirect URIs.
# Format: {"value": "http://127.0.0.1:7070"}  — populated in serve_dashboard().
_STARTUP_BASE_URL: Dict[str, Any] = {}


def get_shared_browser():
    global _GLOBAL_PLAYWRIGHT, _GLOBAL_BROWSER
    with _GLOBAL_BROWSER_LOCK:
        if _GLOBAL_BROWSER is None:
            from playwright.sync_api import sync_playwright
            from .browser import set_shared_browser
            print("[Playwright Pool] Initializing shared browser process...", flush=True)
            _GLOBAL_PLAYWRIGHT = sync_playwright().start()
            _GLOBAL_BROWSER = _GLOBAL_PLAYWRIGHT.chromium.launch(headless=True)
            set_shared_browser(_GLOBAL_PLAYWRIGHT, _GLOBAL_BROWSER)
        return _GLOBAL_PLAYWRIGHT, _GLOBAL_BROWSER

def close_shared_browser():
    global _GLOBAL_PLAYWRIGHT, _GLOBAL_BROWSER
    with _GLOBAL_BROWSER_LOCK:
        if _GLOBAL_BROWSER is not None:
            try:
                _GLOBAL_BROWSER.close()
            except Exception:
                pass
            _GLOBAL_BROWSER = None
        if _GLOBAL_PLAYWRIGHT is not None:
            try:
                _GLOBAL_PLAYWRIGHT.stop()
            except Exception:
                pass
            _GLOBAL_PLAYWRIGHT = None
        from .browser import set_shared_browser
        set_shared_browser(None, None)
        print("[Playwright Pool] Shared browser process stopped.", flush=True)

def find_selectors_for_coordinates(paths: WorkspacePaths, name: str, regions: list) -> list[str]:
    # CSS selector resolution discarded
    return []

def _run_background_ai_training(paths: WorkspacePaths):
    global _ai_training_in_progress, _last_ai_train_time
    try:
        from .ai_training import train_model
        print("[AI Trainer] Starting background automatic training loop...", flush=True)
        model_path = paths.models_dir / "visual_ai.pt"
        train_model(
            paths=paths,
            model_path=model_path,
            epochs=3,
            batch_size=16,
            samples_per_image=2,
            pretrained_backbone=True
        )
        print("[AI Trainer] Background training successfully completed! Model weights updated.", flush=True)
    except Exception as e:
        print(f"[AI Trainer Error] Background training failed: {e}", flush=True)
    finally:
        with _ai_review_queue_lock:
            _ai_training_in_progress = False
            _last_ai_train_time = time.time()

def queue_ai_training_sample(paths: WorkspacePaths):
    global _ai_review_queue_count, _ai_training_in_progress, _last_ai_train_time
    with _ai_review_queue_lock:
        _ai_review_queue_count += 1
        curr_time = time.time()
        # Trigger when we have at least 1 new review, training is not running,
        # and at least 60 seconds have passed since the last training run to avoid CPU starvation.
        if _ai_review_queue_count >= 1 and not _ai_training_in_progress and (curr_time - _last_ai_train_time) > 60:
            _ai_review_queue_count = 0
            _ai_training_in_progress = True
            threading.Thread(target=_run_background_ai_training, args=(paths,), daemon=True).start()


from .config import WorkspacePaths
from .baseline_manager import BaselineManager
from .dashboard_data import build_dashboard_snapshot, _DashboardCache
from .review_manager import ReviewManager
from .integrations_manager import IntegrationsManager
from .sqlite_store import SqliteStore
from .github_oauth import (
    build_authorize_url,
    exchange_code_for_token,
    fetch_github_user,
    oauth_settings,
)



class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, project_root: Path, paths: WorkspacePaths, port: int, **kwargs):
        self.project_root = project_root
        self.paths = paths
        self.port = port
        self.store = SqliteStore(paths.db_path)
        super().__init__(*args, directory=str(project_root), **kwargs)

    def end_headers(self) -> None:  # single authoritative definition — see L208 stub removed
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def _cookie_value(self, name: str) -> str:
        header = self.headers.get("Cookie") or ""
        parts = [item.strip() for item in header.split(";") if item.strip()]
        for part in parts:
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            if k.strip() == name:
                return v.strip()
        return ""

    def _send_set_cookie(self, name: str, value: str, max_age: int | None = None) -> None:
        cookie = f"{name}={value}; Path=/; HttpOnly; SameSite=Lax"
        if max_age is not None:
            cookie += f"; Max-Age={int(max_age)}"
        self.send_header("Set-Cookie", cookie)

    def _clear_cookie(self, name: str) -> None:
        self._send_set_cookie(name, "deleted", max_age=0)

    def _session_user(self):
        token = self._cookie_value("lens_session")
        return self.store.user_for_session(token)

    def _require_role(self, allowed: set[str]) -> bool:
        user = self._session_user()
        return bool(user and user.role in allowed)

    def _send_auth_required(self) -> None:
        self._send_error_json("Authentication required", status=401)

    def _send_forbidden(self) -> None:
        self._send_error_json("Forbidden", status=403)

    def _safe_path(self, base: Path, relative: str) -> str:
        target = (base / relative).resolve()
        base_resolved = base.resolve()
        if base_resolved not in target.parents and target != base_resolved:
            return str(base_resolved)
        return str(target)

    def translate_path(self, path: str) -> str:
        parsed = urlparse(path).path
        frontend_dir = self.project_root / "dashboard_frontend" / "dist"
        
        # Artifacts and baseline paths remain explicitly routed to the storage dirs
        if parsed.startswith("/artifacts/"):
            relative = parsed.removeprefix("/artifacts/")
            return self._safe_path(self.paths.runs_dir, relative)
        if parsed.startswith("/baseline/"):
            relative = parsed.removeprefix("/baseline/")
            return self._safe_path(self.paths.baselines_dir, relative)
            
        # Demo portal pages
        if parsed.startswith("/demo/"):
            relative = parsed.removeprefix("/demo/")
            return self._safe_path(self.project_root / "demo_portal", relative)

        # Assets (JS/CSS/images from vite)
        if parsed.startswith("/assets/"):
            return self._safe_path(frontend_dir, parsed.lstrip("/"))
            
        # API routing happens below in do_GET / do_POST. If it falls through to translate_path,
        # and it's not a known file, we should serve index.html for React Router client side routes.
        # Check if the file exists in the frontend dist dir.
        target_str = self._safe_path(frontend_dir, parsed.lstrip("/"))
        target_path = Path(target_str)
        if target_path.is_file():
            return target_str
            
        # Fallback to index.html for all other paths (except /api/ which should be handled by server)
        return str((frontend_dir / "index.html").resolve())


    # NOTE: end_headers is defined once above (L129).  The duplicate stub that only
    # sent 'Cache-Control: no-store' has been removed to avoid the Python MRO
    # silently picking the last definition, which would have dropped Pragma/Expires.

    def _send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _invalidate_dashboard_cache(self) -> None:
        """Invalidate the dashboard cache after data modifications."""
        _DashboardCache.invalidate()

    def _read_json(self, max_bytes: int = 2 * 1024 * 1024) -> Dict[str, Any]:
        """Read and parse the JSON request body, rejecting oversized payloads."""
        length = int(self.headers.get("Content-Length", "0"))
        if length > max_bytes:
            raise ValueError(f"Request body too large ({length} bytes, max {max_bytes}).")
        body = self.rfile.read(length) if length else b"{}"
        return json.loads(body.decode("utf-8"))

    def _run_cli_action(self, args: list[str]) -> Dict[str, Any]:
        import io
        from contextlib import redirect_stdout, redirect_stderr
        from .cli import main as cli_main

        full_args = list(args)
        if "--root" not in full_args:
            full_args = ["--root", str(self.paths.root)] + full_args

        try:
            get_shared_browser()
        except Exception:
            pass

        stdout_io = io.StringIO()
        stderr_io = io.StringIO()
        returncode = 0
        try:
            with redirect_stdout(stdout_io), redirect_stderr(stderr_io):
                returncode = cli_main(full_args)
                if returncode is None:
                    returncode = 0
        except SystemExit as e:
            returncode = e.code if isinstance(e.code, int) else 0
        except Exception as e:
            import traceback
            traceback.print_exc(file=stderr_io)
            returncode = 1

        return {
            "returncode": returncode,
            "stdout": stdout_io.getvalue(),
            "stderr": stderr_io.getvalue(),
        }

    def _run_cli_action_async(self, args: list[str]) -> str:
        task_id = str(uuid.uuid4())
        _tasks_status[task_id] = {
            "status": "pending",
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "cmd": " ".join(args),
            "created_at": time.time(),
        }

        # Capture project_root by value so the closure doesn't hold a reference to
        # the (already-completed) handler instance after the request finishes.
        _project_root = str(self.project_root)

        def job():
            _tasks_status[task_id]["status"] = "running"
            try:
                process = subprocess.run(
                    [sys.executable, "-m", "visual_regression.cli", *args],
                    cwd=_project_root,
                    capture_output=True,
                    text=True,
                )
                _tasks_status[task_id].update({
                    "status": "completed" if process.returncode == 0 else "failed",
                    "stdout": process.stdout,
                    "stderr": process.stderr,
                    "returncode": process.returncode
                })
                # Call the class method directly — avoids referencing the stale handler `self`
                _DashboardCache.invalidate()
            except Exception as e:
                _tasks_status[task_id].update({
                    "status": "failed",
                    "stderr": str(e),
                    "returncode": -1
                })
            finally:
                # Evict oldest entries if the dict grows too large
                if len(_tasks_status) > _MAX_TASK_HISTORY:
                    oldest_keys = sorted(_tasks_status, key=lambda k: _tasks_status[k].get("created_at", 0))
                    for old_key in oldest_keys[:len(_tasks_status) - _MAX_TASK_HISTORY]:
                        _tasks_status.pop(old_key, None)

        _task_executor.submit(job)
        return task_id

    def _parse_multipart(self) -> Dict[str, Any]:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data"):
            return {}
        
        from email.parser import BytesParser
        from email.policy import default
        
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        
        headers_str = f"Content-Type: {content_type}\r\nContent-Length: {length}\r\n\r\n"
        msg = BytesParser(policy=default).parsebytes(headers_str.encode("utf-8") + body)
        
        parts = {}
        if msg.is_multipart():
            for part in msg.get_payload():
                disp = part.get("Content-Disposition", "")
                import re
                name_match = re.search(r'name="([^"]+)"', disp)
                if not name_match:
                    continue
                name = name_match.group(1)
                
                filename_match = re.search(r'filename="([^"]+)"', disp)
                if filename_match:
                    filename = filename_match.group(1)
                    parts[name] = {
                        "filename": filename,
                        "content": part.get_payload(decode=True),
                        "content_type": part.get_content_type()
                    }
                else:
                    payload = part.get_payload(decode=True)
                    parts[name] = payload.decode("utf-8") if payload else ""
        return parts

    def _send_error_json(self, message: str, status: int = 400, **extra: Any) -> None:
        payload = {"ok": False, "error": message}
        payload.update(extra)
        self._send_json(payload, status=status)

    def _send_cli_result(self, result: Dict[str, Any]) -> None:
        status = 200 if result.get("returncode", 1) == 0 else 500
        payload = {"ok": result.get("returncode", 1) == 0, **result}
        self._send_json(payload, status=status)

    def _send_redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def _dashboard_base_url(self) -> str:
        # Prefer the startup-fixed base URL to avoid Host-header injection.
        # Falls back to the Host header only for local development.
        fixed = _STARTUP_BASE_URL.get("value")
        if fixed:
            return fixed
        host = self.headers.get("Host") or f"127.0.0.1:{self.port}"
        return f"http://{host}"

    def _github_repo_url(self) -> str:
        # Use the URL cached at server startup (see serve_dashboard).
        # Falls back to a live subprocess call if the cache is empty.
        cached = _GITHUB_REPO_URL_CACHE.get("value")
        if cached is not None:
            return cached
        process = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(self.project_root),
            capture_output=True,
            text=True,
        )
        result = process.stdout.strip() if process.returncode == 0 else ""
        _GITHUB_REPO_URL_CACHE["value"] = result
        return result

    def _is_authorized(self) -> bool:
        """
        Backward compatible authorization check.

        - Browser users: cookie session (admin) OR role checks via _require_role()
        - Automation: X-Access-Key matches configured api_key

        The API key is cached for up to 60 s to avoid reading integrations.json
        on every single request (RISK-01 fix).
        Uses hmac.compare_digest for timing-safe comparison (prevents timing attacks).
        """
        user = self._session_user()
        if user and user.role == "admin":
            return True
        now = time.time()
        with _API_KEY_LOCK:
            cached = _API_KEY_CACHE
            if cached.get("expires_at", 0) > now:
                secure_key = cached["value"]
            else:
                manager = IntegrationsManager(self.paths.root)
                secure_key = manager.get_config().get("api_key", "")
                cached["value"] = secure_key
                cached["expires_at"] = now + _API_KEY_TTL
        incoming = self.headers.get("X-Access-Key") or ""
        # Use timing-safe comparison to prevent timing-based key enumeration attacks
        return bool(secure_key) and hmac.compare_digest(incoming, secure_key)

    @staticmethod
    def _payload_to_args(payload: Dict[str, Any], allowed: Dict[str, str]) -> list[str]:
        args: list[str] = []
        for key, cli_name in allowed.items():
            value = payload.get(key)
            if value is None or value == "":
                continue

            # Normalize browser values (e.g. Chrome -> chromium, Safari -> webkit)
            if key in {"browser", "browsers"}:
                if isinstance(value, str):
                    val_lower = value.strip().lower()
                    if val_lower == "chrome":
                        value = "chromium"
                    elif val_lower == "safari":
                        value = "webkit"
                    else:
                        value = val_lower
                elif isinstance(value, list):
                    value = [
                        "chromium" if str(item).strip().lower() == "chrome"
                        else "webkit" if str(item).strip().lower() == "safari"
                        else str(item).strip().lower()
                        for item in value
                    ]

            # Normalize device values (e.g. Desktop -> empty string to use default desktop)
            if key in {"device", "devices"}:
                if isinstance(value, str):
                    if value.strip().lower() == "desktop":
                        value = ""
                elif isinstance(value, list):
                    value = [
                        "" if str(item).strip().lower() == "desktop" else str(item)
                        for item in value
                    ]

            if value == "":
                continue

            if isinstance(value, bool):
                if value:
                    args.append(cli_name)
                continue
            if isinstance(value, list):
                for item in value:
                    args.extend([cli_name, str(item)])
                continue
            args.extend([cli_name, str(value)])
        return args

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            
            # Dynamically inject visual defect in CI to test pipeline failure/interception
            if parsed.path == "/demo/styles.css":
                import os
                if os.environ.get("GITHUB_ACTIONS") == "true":
                    css_path = Path(self.translate_path(self.path))
                    if css_path.is_file():
                        content = css_path.read_text(encoding="utf-8")
                        content = content.replace("--brand: #0f5f8f;", "--brand: #ef4444;")
                        content_bytes = content.encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "text/css; charset=utf-8")
                        self.send_header("Content-Length", str(len(content_bytes)))
                        self.end_headers()
                        self.wfile.write(content_bytes)
                        return

            if parsed.path.startswith("/artifacts/") or parsed.path.startswith("/baseline/"):
                if not self._session_user() and not self._is_authorized():
                    return self._send_forbidden()

            if parsed.path == "/api/health":
                return self._send_json({"ok": True, "status": "healthy"})

            if parsed.path == "/api/tasks/status":
                query = parse_qs(parsed.query)
                task_id = query.get("id", [None])[0]
                if not task_id:
                    return self._send_error_json("Missing task id", status=400)
                status = _tasks_status.get(task_id)
                if not status:
                    return self._send_error_json("Task not found", status=404)
                return self._send_json({"ok": True, "task": status})

            if parsed.path == "/api/auth/me":
                user = self._session_user()
                if not user:
                    return self._send_json({"ok": True, "authenticated": False, "user": None})
                return self._send_json(
                    {"ok": True, "authenticated": True, "user": {"email": user.email, "role": user.role, "name": user.display_name}}
                )
            if parsed.path == "/api/integrations/github/status":
                manager = IntegrationsManager(self.paths.root)
                settings = oauth_settings(f"{self._dashboard_base_url()}/api/integrations/github/callback")
                return self._send_json(
                    {
                        "configured": settings["configured"],
                        "redirect_uri": settings["redirect_uri"],
                        "repo_url": self._github_repo_url(),
                        **manager.github_status(),
                    }
                )

            if parsed.path == "/api/integrations/github/callback":
                manager = IntegrationsManager(self.paths.root)
                query = parse_qs(parsed.query)
                if query.get("error"):
                    error_value = query.get("error_description", query.get("error", ["Authorization failed"]))[0]
                    manager.log_activity(
                        message=f"GitHub OAuth failed: {error_value}",
                        branch="integrations",
                        status="failed",
                    )
                    return self._send_redirect(f"/integrations?github_error={quote_plus(error_value)}")

                code = query.get("code", [None])[0]
                state = query.get("state", [None])[0]
                if not code or not state:
                    return self._send_redirect("/integrations?github_error=Missing+code+or+state")
                if not manager.validate_github_state(state):
                    manager.log_activity(message="GitHub OAuth failed: invalid state", branch="integrations", status="failed")
                    return self._send_redirect("/integrations?github_error=Invalid+or+expired+state")

                settings = oauth_settings(f"{self._dashboard_base_url()}/api/integrations/github/callback")
                if not settings["configured"]:
                    return self._send_redirect("/integrations?github_error=GitHub+OAuth+is+not+configured")

                token_payload = exchange_code_for_token(
                    client_id=settings["client_id"],
                    client_secret=settings["client_secret"],
                    code=code,
                    redirect_uri=settings["redirect_uri"],
                )
                if "error" in token_payload:
                    error_value = token_payload.get("error_description") or token_payload.get("error") or "Unable to exchange OAuth code"
                    manager.log_activity(
                        message=f"GitHub OAuth failed: {error_value}",
                        branch="integrations",
                        status="failed",
                    )
                    return self._send_redirect(f"/integrations?github_error={quote_plus(error_value)}")

                access_token = token_payload.get("access_token", "")
                scopes = [scope for scope in str(token_payload.get("scope", "")).split(",") if scope]
                if not access_token:
                    return self._send_redirect("/integrations?github_error=Missing+access+token")
                user = fetch_github_user(access_token)
                manager.complete_github_oauth(access_token=access_token, user=user, scopes=scopes)
                return self._send_redirect("/integrations?github=connected")

            if parsed.path == "/api/dashboard":
                snapshot = build_dashboard_snapshot(self.project_root, self.paths)
                return self._send_json(snapshot)

            if parsed.path == "/api/run":
                query = parse_qs(parsed.query)
                run = query.get("id", [None])[0]
                if not run:
                    return self._send_error_json("Missing run id", status=400)
                manager = ReviewManager(self.paths)
                run_dir = manager.resolve_run_dir(run)
                payload = manager.load_run_payload(run_dir)
                payload["report_href"] = f"/artifacts/{run_dir.name}/report.html"
                from .dashboard_data import _normalize_review_status, _sanitize_ai_label

                result = payload.get("result") or {}
                decision = payload.get("decision") or payload.get("review") or {}
                payload["review_status"] = _normalize_review_status(
                    payload.get("status"),
                    decision.get("status"),
                    mismatch_pct=result.get("mismatch_pct"),
                    threshold_pct=payload.get("threshold_pct"),
                )
                ai_assessment = dict(payload.get("ai_assessment") or {})
                ai_assessment["label"] = _sanitize_ai_label(ai_assessment.get("label"))
                payload["ai_assessment"] = ai_assessment
                return self._send_json(payload)

            if parsed.path == "/api/baseline":
                query = parse_qs(parsed.query)
                baseline_id = query.get("id", [None])[0]
                if not baseline_id:
                    return self._send_error_json("Missing baseline id", status=400)
                manager = BaselineManager(self.paths)
                payload = manager.get_baseline_details(baseline_id)
                return self._send_json(payload)

            if parsed.path == "/api/integrations":
                manager = IntegrationsManager(self.paths.root)
                config = manager.get_config()
                # Mask key but provide other info
                token = config.get("api_key", "")
                masked_token = (token[:7] + "*" * 20) if len(token) > 10 else "********"
                settings = oauth_settings(f"{self._dashboard_base_url()}/api/integrations/github/callback")
                return self._send_json({
                    "webhook_url": config.get("webhook_url", ""),
                    "webhook_threshold": config.get("webhook_threshold", 1.0),
                    "api_key": masked_token,
                    "webhook_connected": bool(config.get("webhook_url")),
                    "activity_count": len(config.get("activity", [])),
                    "github_configured": settings["configured"],
                })

            if parsed.path == "/api/audit":
                user = self._session_user()
                if not user or user.role not in {"admin", "developer"}:
                    return self._send_auth_required()
                limit = int(parse_qs(parsed.query).get("limit", ["200"])[0])
                logs = self.store.get_audit_logs(limit=limit)
                return self._send_json({"logs": logs})

            if parsed.path == "/api/integrations/activity":
                manager = IntegrationsManager(self.paths.root)
                config = manager.get_config()
                return self._send_json({"activity": config.get("activity", [])})

            if parsed.path == "/api/users":
                user = self._session_user()
                if not user:
                    return self._send_auth_required()
                if not self._require_role({"admin"}):
                    return self._send_forbidden()
                users = self.store.list_users()
                return self._send_json({"ok": True, "users": users})

            if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/export"):
                run_id = parsed.path.removeprefix("/api/runs/").removesuffix("/export")
                if not run_id or "/" in run_id or ".." in run_id:
                    return self._send_error_json("Invalid run id", status=400)
                run_dir = self.paths.runs_dir / run_id
                if not run_dir.is_dir():
                    return self._send_error_json(f"Run '{run_id}' not found", status=404)
                from .export_report import generate_standalone_report
                html_content = generate_standalone_report(run_dir)
                html_bytes = html_content.encode("utf-8")
                safe_name = run_id[:64].replace("/", "_").replace("\\", "_")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html_bytes)))
                self.send_header("Content-Disposition", f'attachment; filename="report-{safe_name}.html"')
                self.end_headers()
                self.wfile.write(html_bytes)
                return

            return super().do_GET()

        except FileNotFoundError as exc:
            return self._send_error_json(str(exc), status=404)
        except ValueError as exc:
            return self._send_error_json(str(exc), status=400)
        except Exception as exc:
            return self._send_error_json(str(exc), status=500)

    def do_POST(self) -> None:  # noqa: N802
        try:
            if self.path == "/api/runs/upload":
                if not self._is_authorized() and not self._session_user():
                    return self._send_forbidden()
                
                parts = self._parse_multipart()
                from .server_services import handle_run_upload
                try:
                    res = handle_run_upload(
                        paths=self.paths,
                        project_root=self.project_root,
                        parts=parts,
                        github_repo_url=self._github_repo_url(),
                        dashboard_base_url=self._dashboard_base_url(),
                    )
                    self._invalidate_dashboard_cache()
                    return self._send_json(res)
                except ValueError as exc:
                    return self._send_error_json(str(exc), status=400)
                except FileNotFoundError as exc:
                    return self._send_error_json(str(exc), status=404)
                except Exception as exc:
                    return self._send_error_json(str(exc), status=500)


            if self.path == "/api/auth/login":
                payload = self._read_json()
                email = str(payload.get("email", "")).strip()
                # NOTE: do NOT strip the password — leading/trailing spaces are valid password chars
                password = str(payload.get("password", ""))
                if not email or not password:
                    return self._send_error_json("Email and password are required", status=400)

                # Brute-force / rate-limiting: max 10 attempts per IP per minute
                client_ip = self.client_address[0]
                now_ts = time.time()
                window_start_ts = now_ts - 60.0
                with _LOGIN_LIMITER_LOCK:
                    recent = [t for t in _LOGIN_LIMITER[client_ip] if t > window_start_ts]
                    if len(recent) >= _MAX_LOGIN_ATTEMPTS_PER_MINUTE:
                        return self._send_error_json(
                            "Too many login attempts. Please wait a minute before trying again.",
                            status=429,
                        )
                    recent.append(now_ts)
                    _LOGIN_LIMITER[client_ip] = recent

                user = self.store.authenticate(email, password)
                if not user:
                    self.store.audit(None, None, "auth.login_failed", {"email": email})
                    return self._send_error_json("Invalid credentials", status=401)

                # Successful login — clear limiter for this IP
                with _LOGIN_LIMITER_LOCK:
                    _LOGIN_LIMITER.pop(client_ip, None)

                token = self.store.create_session(user.email, ttl_seconds=60 * 60 * 12)
                self.send_response(200)
                self._send_set_cookie("lens_session", token, max_age=60 * 60 * 12)
                body = json.dumps({"ok": True, "user": {"email": user.email, "role": user.role}}, indent=2).encode(
                    "utf-8"
                )
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                self.store.audit(user.email, user.role, "auth.login", {"email": user.email})
                return

            if self.path == "/api/auth/logout":
                token = self._cookie_value("lens_session")
                if token:
                    user = self.store.user_for_session(token)
                    if user:
                        self.store.audit(user.email, user.role, "auth.logout", {"email": user.email})
                    self.store.delete_session(token)
                self.send_response(200)
                self._clear_cookie("lens_session")
                body = json.dumps({"ok": True}, indent=2).encode("utf-8")
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path in {"/api/review", "/api/decision", "/api/actions/review"}:
                if not self._require_role({"admin"}):
                    if not self._is_authorized():
                        return self._send_forbidden()
                    
                payload = self._read_json()
                run_ref = str(payload.get("run", "")).strip()
                decision_value = str(payload.get("decision", "")).strip()
                decider = str(payload.get("reviewer", "") or payload.get("decider", "")).strip()
                if not run_ref:
                    return self._send_error_json("Missing run id", status=400)
                if decision_value not in {"approved", "rejected"}:
                    return self._send_error_json("Decision must be approved or rejected", status=400)
                if not decider:
                    return self._send_error_json("Decider is required", status=400)
                manager = ReviewManager(self.paths)
                run_dir = manager.resolve_run_dir(run_ref)
                decision = manager.save_decision(
                    run_dir=run_dir,
                    decision=decision_value,
                    decider=decider,
                    comment=str(payload.get("comment", "")),
                )
                
                # Auto-update GitHub Commit Status if integrated
                try:
                    run_payload = manager.load_run_payload(run_dir)
                    build_id = run_payload.get("build_id")
                    if build_id:
                        build_dir = self.paths.builds_dir / build_id
                        build_json_file = build_dir / "build.json"
                        if build_json_file.exists():
                            build_meta = json.loads(build_json_file.read_text(encoding="utf-8"))
                            commit_sha = build_meta.get("commit_sha")
                            if commit_sha:
                                # Retrieve all runs matching this build_id
                                all_runs = []
                                for r_dir in self.paths.runs_dir.iterdir():
                                    if not r_dir.is_dir():
                                        continue
                                    res_file = r_dir / "result.json"
                                    if res_file.exists():
                                        try:
                                            r_payload = json.loads(res_file.read_text(encoding="utf-8"))
                                            if r_payload.get("build_id") == build_id:
                                                all_runs.append(r_payload)
                                        except Exception:
                                            pass
                                
                                # A build is green if all runs are either PASS or manually approved
                                failed_any = False
                                for r_payload in all_runs:
                                    status = r_payload.get("status")
                                    dec_status = (r_payload.get("decision") or {}).get("status")
                                    if status == "FAIL" and dec_status != "approved":
                                        failed_any = True
                                        break
                                
                                state = "failure" if failed_any else "success"
                                description = "Visual check: All snapshots approved/passed" if not failed_any else "Visual check: Remaining unapproved mismatches"
                                
                                integrations_manager = IntegrationsManager(self.paths.root)
                                github_config = integrations_manager.get_config().get("github", {})
                                if github_config.get("connected"):
                                    repo_url = self._github_repo_url()
                                    if repo_url:
                                        from urllib.parse import quote
                                        target_url = f"{self._dashboard_base_url()}/build/{quote(build_id)}"
                                        integrations_manager.post_github_commit_status(
                                            repo_url=repo_url,
                                            sha=commit_sha,
                                            state=state,
                                            target_url=target_url,
                                            description=description
                                        )
                except Exception as e:
                    print(f"[GitHub Status Update Warning] Failed: {e}", flush=True)

                actor = self._session_user()
                self.store.audit(
                    actor.email if actor else decider,
                    actor.role if actor else None,
                    f"decision.{decision_value}",
                    {"run": run_ref, "decider": decider, "comment": str(payload.get("comment", ""))},
                )
                self._invalidate_dashboard_cache()
                queue_ai_training_sample(self.paths)
                return self._send_json({"ok": True, "decision": decision})

            if self.path == "/api/run/delete":
                if not self._require_role({"admin"}):
                    if not self._is_authorized():
                        return self._send_forbidden()
                payload = self._read_json()
                run_ref = str(payload.get("run", "")).strip()
                if not run_ref:
                    return self._send_error_json("Missing run id", status=400)
                manager = ReviewManager(self.paths)
                result = manager.delete_run(run_ref)
                self._invalidate_dashboard_cache()
                return self._send_json({"ok": True, **result})

            if self.path == "/api/baseline/update-threshold":
                if not self._require_role({"admin", "developer"}):
                    if not self._is_authorized():
                        return self._send_forbidden()
                payload = self._read_json()
                name = str(payload.get("name", "")).strip()
                threshold_val = payload.get("threshold_pct")
                if not name:
                    return self._send_error_json("Missing baseline name", status=400)
                
                manager = BaselineManager(self.paths)
                try:
                    if threshold_val is None or str(threshold_val).strip() == "":
                        manager.save_custom_threshold(name, None)
                    else:
                        manager.save_custom_threshold(name, float(threshold_val))
                    self._invalidate_dashboard_cache()
                    return self._send_json({"ok": True})
                except Exception as e:
                    return self._send_error_json(str(e), status=400)

            if self.path == "/api/baseline/delete":
                if not self._require_role({"admin"}):
                    if not self._is_authorized():
                        return self._send_forbidden()
                payload = self._read_json()
                name = str(payload.get("name", "")).strip()
                if not name:
                    return self._send_error_json("Missing baseline name", status=400)
                manager = BaselineManager(self.paths)
                result = manager.delete_baseline(name)
                self._invalidate_dashboard_cache()
                return self._send_json({"ok": True, **result})

            if self.path == "/api/baseline/restore":
                if not self._require_role({"admin"}):
                    if not self._is_authorized():
                        return self._send_forbidden()
                payload = self._read_json()
                name = str(payload.get("name", "")).strip()
                version = str(payload.get("version", "")).strip()
                if not name or not version:
                    return self._send_error_json("Baseline name and version are required", status=400)
                manager = BaselineManager(self.paths)
                result = manager.restore_version(
                    name=name,
                    version=version,
                    restored_by=str(payload.get("restored_by", "")) or None,
                )
                self._invalidate_dashboard_cache()
                return self._send_json({"ok": True, **result})

            if self.path == "/api/ignore-regions":
                if not self._is_authorized() and not self._require_role({"admin", "viewer"}):
                    return self._send_forbidden()
                payload = self._read_json()
                name = str(payload.get("name", "")).strip()
                run_id = str(payload.get("run_id", "")).strip()
                ignore_regions = payload.get("ignore_regions", [])
                if not name:
                    return self._send_error_json("Missing baseline name", status=400)
                
                from .server_services import handle_ignore_regions_update
                try:
                    res = handle_ignore_regions_update(
                        paths=self.paths,
                        name=name,
                        run_id=run_id,
                        ignore_regions=ignore_regions,
                        find_selectors_fn=find_selectors_for_coordinates,
                        github_repo_url=self._github_repo_url(),
                        dashboard_base_url=self._dashboard_base_url(),
                    )
                    self._invalidate_dashboard_cache()
                    return self._send_json(res)
                except Exception as e:
                    return self._send_error_json(str(e), status=500)

            if self.path == "/api/ignore-css-selectors":
                if not self._is_authorized() and not self._require_role({"admin", "viewer"}):
                    return self._send_forbidden()
                return self._send_json({"ok": True, "ignore_css_selectors": []})

            if self.path == "/api/actions/create-demo-baselines":
                if not self._require_role({"admin", "developer"}) and not self._is_authorized():
                    return self._send_forbidden()

                result = self._run_cli_action(["create-suite-baselines", "--suite", "suite.demo.yaml", "--overwrite"])
                self._invalidate_dashboard_cache()
                return self._send_cli_result(result)

            if self.path == "/api/actions/train-ai":
                if not self._require_role({"admin", "developer"}) and not self._is_authorized():
                    return self._send_forbidden()
                result = self._run_cli_action(["train-ai", "--epochs", "20", "--samples-per-image", "12"])
                self._invalidate_dashboard_cache()
                return self._send_cli_result(result)

            if self.path == "/api/actions/compare-defect":
                if not self._require_role({"admin", "developer"}) and not self._is_authorized():
                    return self._send_forbidden()
                defect_url = f"http://127.0.0.1:{self.port}/demo/index.html?lang=en-US&defect=missing-cta"
                result = self._run_cli_action(["compare", "--name", "demo-home-en", "--url", defect_url])
                self._invalidate_dashboard_cache()
                return self._send_cli_result(result)

            if self.path == "/api/actions/create-baseline":
                # Developer+ can capture baselines; CI may use API key only.
                if not self._require_role({"admin", "developer"}):
                    if not self._is_authorized():
                        return self._send_forbidden()
                payload = self._read_json()
                args = [
                    "create-baseline",
                    "--name",
                    str(payload.get("name", "")),
                ]
                args.extend(
                    self._payload_to_args(
                        payload,
                        {
                            "url": "--url",
                            "image": "--image",
                            "browser": "--browser",
                            "device": "--device",
                            "viewport": "--viewport",
                            "wait_ms": "--wait-ms",
                            "locale": "--locale",
                            "timezone_id": "--timezone-id",
                            "color_scheme": "--color-scheme",
                            "updated_by": "--updated-by",
                        },
                    )
                )
                result = self._run_cli_action(args)
                self._invalidate_dashboard_cache()
                return self._send_cli_result(result)

            if self.path == "/api/actions/create-multiple-baselines":
                if not self._require_role({"admin", "developer"}) and not self._is_authorized():
                    return self._send_forbidden()
                payload = self._read_json()
                args = [
                    "create-multiple-baselines",
                    "--url",
                    str(payload.get("url", "")),
                    "--page-limit",
                    str(payload.get("page_limit", 30)),
                ]
                args.extend(
                    self._payload_to_args(
                        payload,
                        {
                            "browser": "--browser",
                            "device": "--device",
                            "viewport": "--viewport",
                            "wait_ms": "--wait-ms",
                            "locale": "--locale",
                            "timezone_id": "--timezone-id",
                            "color_scheme": "--color-scheme",
                            "updated_by": "--updated-by",
                        },
                    )
                )
                if payload.get("preserve_query"):
                    args.append("--preserve-query")
                if payload.get("overwrite"):
                    args.append("--overwrite")
                if payload.get("fail_fast"):
                    args.append("--fail-fast")
                result = self._run_cli_action(args)
                self._invalidate_dashboard_cache()
                return self._send_cli_result(result)

            if self.path == "/api/actions/update-baseline":
                if not self._require_role({"admin"}):
                    if not self._is_authorized():
                        return self._send_forbidden()
                payload = self._read_json()
                args = [
                    "update-baseline",
                    "--name",
                    str(payload.get("name", "")),
                ]
                args.extend(
                    self._payload_to_args(
                        payload,
                        {
                            "url": "--url",
                            "image": "--image",
                            "browser": "--browser",
                            "device": "--device",
                            "viewport": "--viewport",
                            "wait_ms": "--wait-ms",
                            "locale": "--locale",
                            "timezone_id": "--timezone-id",
                            "color_scheme": "--color-scheme",
                            "updated_by": "--updated-by",
                        },
                    )
                )
                result = self._run_cli_action(args)
                self._invalidate_dashboard_cache()
                return self._send_cli_result(result)

            if self.path == "/api/actions/compare":
                if not self._require_role({"admin", "developer"}):
                    if not self._is_authorized():
                        return self._send_forbidden()
                payload = self._read_json()
                browsers = payload.get("browsers") or []
                devices = payload.get("devices") or []
                locales = payload.get("locales") or []

                if any((len(browsers) > 1, len(devices) > 1, len(locales) > 1)):
                    args = [
                        "compare-matrix",
                        "--name",
                        str(payload.get("name", "")),
                    ]
                    if payload.get("url"):
                        args.extend(["--url", str(payload.get("url"))])
                    for browser in browsers:
                        args.extend(["--browser", str(browser)])
                    for device in devices:
                        args.extend(["--device", str(device)])
                    for locale in locales:
                        args.extend(["--locale", str(locale)])
                    args.extend(
                        self._payload_to_args(
                            payload,
                            {
                                "viewport": "--viewport",
                                "wait_ms": "--wait-ms",
                                "timezone_id": "--timezone-id",
                                "color_scheme": "--color-scheme",
                                "threshold_pct": "--threshold-pct",
                                "pixel_threshold": "--pixel-threshold",
                                "min_region_area": "--min-region-area",
                                "comparison_mode": "--comparison-mode",
                            },
                        )
                    )
                    if payload.get("no_ai"):
                        args.append("--no-ai")
                    if payload.get("fail_fast"):
                        args.append("--fail-fast")
                    result = self._run_cli_action(args)
                    self._invalidate_dashboard_cache()
                    return self._send_cli_result(result)

                effective_payload = dict(payload)
                if browsers:
                    effective_payload["browser"] = browsers[0]
                if devices:
                    effective_payload["device"] = "" if devices[0] == "desktop" else devices[0]
                if locales:
                    effective_payload["locale"] = locales[0]
                args = [
                    "compare",
                    "--name",
                    str(payload.get("name", "")),
                ]
                args.extend(
                    self._payload_to_args(
                        effective_payload,
                        {
                            "url": "--url",
                            "browser": "--browser",
                            "device": "--device",
                            "viewport": "--viewport",
                            "wait_ms": "--wait-ms",
                            "locale": "--locale",
                            "timezone_id": "--timezone-id",
                            "color_scheme": "--color-scheme",
                            "threshold_pct": "--threshold-pct",
                            "pixel_threshold": "--pixel-threshold",
                            "min_region_area": "--min-region-area",
                            "comparison_mode": "--comparison-mode",
                        },
                    )
                )
                if payload.get("no_ai"):
                    args.append("--no-ai")
                result = self._run_cli_action(args)
                self._invalidate_dashboard_cache()
                return self._send_cli_result(result)

            if self.path == "/api/integrations/webhooks":
                if not self._require_role({"admin"}):
                    if not self._is_authorized():
                        return self._send_forbidden()
                payload = self._read_json()
                url = str(payload.get("url", "")).strip()
                threshold = float(payload.get("threshold", 1.0))
                manager = IntegrationsManager(self.paths.root)
                manager.update_webhook(url, threshold)
                self._invalidate_dashboard_cache()
                return self._send_json({"ok": True})

            if self.path == "/api/integrations/rotate-key":
                if not self._require_role({"admin"}):
                    if not self._is_authorized():
                        return self._send_forbidden()
                manager = IntegrationsManager(self.paths.root)
                new_key = manager.rotate_api_key()
                # Immediately invalidate the in-process API key cache so the
                # new key is enforced on the very next request (no 60s lag).
                with _API_KEY_LOCK:
                    _API_KEY_CACHE.clear()
                return self._send_json({"ok": True, "api_key": new_key})

            if self.path == "/api/integrations/reveal-key":
                if not self._require_role({"admin"}):
                    if not self._is_authorized():
                        return self._send_forbidden()
                manager = IntegrationsManager(self.paths.root)
                return self._send_json({"ok": True, "api_key": manager.reveal_api_key()})

            if self.path == "/api/integrations/test-webhook":
                if not self._require_role({"admin"}):
                    if not self._is_authorized():
                        return self._send_forbidden()
                payload = self._read_json()
                url = str(payload.get("url", "")).strip()
                if not url:
                    return self._send_error_json("Webhook URL is required", status=400)
                from .notifier import trigger_webhook_detailed
                result = trigger_webhook_detailed(url, {"event": "test_ping", "message": "The Lens Integration Test"})
                manager = IntegrationsManager(self.paths.root)
                manager.log_activity(
                    message="Webhook test succeeded" if result.get("ok") else "Webhook test failed",
                    branch="integrations",
                    status="success" if result.get("ok") else "failed",
                )
                return self._send_json(result, status=200 if result.get("ok") else 400)

            if self.path == "/api/integrations/github/connect":
                if not self._require_role({"admin"}):
                    if not self._is_authorized():
                        return self._send_forbidden()
                manager = IntegrationsManager(self.paths.root)
                settings = oauth_settings(f"{self._dashboard_base_url()}/api/integrations/github/callback")
                if not settings["configured"]:
                    return self._send_error_json(
                        "GitHub OAuth is not configured. Set GITHUB_OAUTH_CLIENT_ID and GITHUB_OAUTH_CLIENT_SECRET on the dashboard server.",
                        status=400,
                    )
                state = manager.begin_github_oauth()
                authorize_url = build_authorize_url(
                    client_id=settings["client_id"],
                    redirect_uri=settings["redirect_uri"],
                    state=state,
                    scope=settings["scope"],
                )
                return self._send_json({"ok": True, "authorize_url": authorize_url})

            if self.path == "/api/integrations/github/disconnect":
                if not self._require_role({"admin"}):
                    if not self._is_authorized():
                        return self._send_forbidden()
                manager = IntegrationsManager(self.paths.root)
                manager.disconnect_github()
                return self._send_json({"ok": True})

            if self.path == "/api/users":
                user = self._session_user()
                if not user:
                    return self._send_auth_required()
                if not self._require_role({"admin"}):
                    return self._send_forbidden()
                payload = self._read_json()
                email = str(payload.get("email", "")).strip()
                password = str(payload.get("password", "")).strip()
                role = str(payload.get("role", "viewer")).strip()
                name = str(payload.get("name", "")).strip()
                if not email or not password:
                    return self._send_error_json("Email and password are required", status=400)
                try:
                    self.store.create_user(email, password, role=role, display_name=name)
                except ValueError as exc:
                    return self._send_error_json(str(exc), status=400)
                except Exception:
                    return self._send_error_json("User already exists", status=409)
                actor = self._session_user()
                self.store.audit(
                    actor.email if actor else None,
                    actor.role if actor else None,
                    "users.create",
                    {"email": email, "role": role},
                )
                return self._send_json({"ok": True})

            if self.path == "/api/users/delete":
                user = self._session_user()
                if not user:
                    return self._send_auth_required()
                if not self._require_role({"admin"}):
                    return self._send_forbidden()
                payload = self._read_json()
                email = str(payload.get("email", "")).strip()
                if not email:
                    return self._send_error_json("Email is required", status=400)
                actor = self._session_user()
                if actor and actor.email == email.lower():
                    return self._send_error_json("Cannot delete your own account", status=400)
                all_users = self.store.list_users()
                target = next((u for u in all_users if u.get("email", "").lower() == email.lower()), None)
                if target and target.get("role") == "admin":
                    admin_count = sum(1 for u in all_users if u.get("role") == "admin")
                    if admin_count <= 1:
                        return self._send_error_json("Cannot delete the last admin account", status=400)
                self.store.delete_user(email)
                self.store.audit(
                    actor.email if actor else None,
                    actor.role if actor else None,
                    "users.delete",
                    {"email": email},
                )
                return self._send_json({"ok": True})

            if self.path == "/api/users/update":
                user = self._session_user()
                if not user:
                    return self._send_auth_required()
                if not self._require_role({"admin"}):
                    return self._send_forbidden()
                payload = self._read_json()
                email = str(payload.get("email", "")).strip()
                if not email:
                    return self._send_error_json("Email is required", status=400)
                role = payload.get("role")
                disabled = payload.get("disabled")
                password = payload.get("password")
                display_name = payload.get("display_name")
                if role is not None:
                    role = str(role).strip()
                if password is not None:
                    password = str(password).strip() or None
                if display_name is not None:
                    display_name = str(display_name).strip()
                try:
                    self.store.update_user(
                        email,
                        role=role if role else None,
                        disabled=bool(disabled) if disabled is not None else None,
                        password=password,
                        display_name=display_name,
                    )
                except ValueError as exc:
                    return self._send_error_json(str(exc), status=400)
                actor = self._session_user()
                self.store.audit(
                    actor.email if actor else None,
                    actor.role if actor else None,
                    "users.update",
                    {"email": email},
                )
                return self._send_json({"ok": True})

            if self.path == "/api/sdk/snapshot":
                if not self._is_authorized() and not self._session_user():
                    return self._send_forbidden()
                
                # Payload size protection (10MB limit)
                content_len = int(self.headers.get("Content-Length", "0"))
                if content_len > 10 * 1024 * 1024:
                    return self._send_error_json("Payload too large. Maximum 10MB.", status=413)

                # Rate Limiting protection (thread-safe via _SDK_LIMITER_LOCK)
                auth_hdr = self.headers.get("Authorization") or ""
                client_ip = self.client_address[0]
                limiter_key = auth_hdr if auth_hdr else client_ip
                now = time.time()
                window_start = now - 60.0
                with _SDK_LIMITER_LOCK:
                    timestamps = [t for t in _SDK_LIMITER[limiter_key] if t > window_start]
                    if len(timestamps) >= _MAX_SNAPSHOTS_PER_MINUTE:
                        return self._send_error_json("Rate limit exceeded. Maximum 30 uploads per minute.", status=429)
                    timestamps.append(now)
                    _SDK_LIMITER[limiter_key] = timestamps

                payload = self._read_json(max_bytes=10 * 1024 * 1024)
                name = str(payload.get("name", "")).strip()
                image_b64 = str(payload.get("image", "")).strip()
                if not name:
                    return self._send_error_json("Missing 'name'", status=400)
                # Security: reject path traversal sequences in the baseline name (RISK-03)
                if ".." in name or "/" in name or "\\" in name:
                    return self._send_error_json(
                        "Invalid baseline name: must not contain path separators or '..'",
                        status=400,
                    )
                if not image_b64:
                    return self._send_error_json("Missing 'image' (base64 PNG)", status=400)


                import base64 as _base64
                try:
                    # Strip data URI prefix if present
                    if "," in image_b64:
                        image_b64 = image_b64.split(",", 1)[1]
                    image_bytes = _base64.b64decode(image_b64)
                except Exception:
                    return self._send_error_json("Invalid base64 image data", status=400)

                manager = BaselineManager(self.paths)

                # Create baseline if it doesn't exist
                if not manager.exists(name):
                    tmp_dir = self.paths.root / "tmp"
                    tmp_dir.mkdir(parents=True, exist_ok=True)
                    tmp_path = tmp_dir / f"sdk_baseline_{name}.png"
                    tmp_path.write_bytes(image_bytes)
                    from .config import CaptureConfig
                    from .cli import build_capture_metadata
                    url = str(payload.get("url", "")) or "sdk://upload"
                    browser = str(payload.get("browser", "sdk-client"))
                    mock_cfg = CaptureConfig(
                        name=name, url=url, browser=browser,
                        viewport=(int(payload.get("viewport_width", 1440)), int(payload.get("viewport_height", 900))),
                    )
                    capture_meta = {**build_capture_metadata(mock_cfg), "updated_by": "sdk", "source": "sdk-upload"}
                    try:
                        manager.save_from_image(name=name, source_image_path=tmp_path, capture_meta=capture_meta)
                    finally:
                        tmp_path.unlink(missing_ok=True)
                    self._invalidate_dashboard_cache()
                    return self._send_json({
                        "ok": True,
                        "action": "baseline_created",
                        "name": name,
                        "message": f"Baseline '{name}' created successfully from SDK upload."
                    })

                # Compare against existing baseline
                from .cli import _copy_baseline_into_run, now_stamp_precise, summarize_severity, build_ai_explanation, resolve_ai_model_path, build_capture_metadata, _initial_decision_status
                from .image_compare import compare_images
                from .decision import decide_pass_fail
                from .reporter import generate_html_report, save_image, write_json
                from .ai_training import assess_result
                from .config import CaptureConfig
                from .baseline_manager import BaselineManager as BM

                url = str(payload.get("url", "")) or "sdk://upload"
                browser = str(payload.get("browser", "sdk-client"))
                threshold_pct = float(payload.get("threshold_pct", 0.5))
                pixel_threshold = int(payload.get("pixel_threshold", 20))
                min_region_area = int(payload.get("min_region_area", 120))
                comparison_mode = str(payload.get("comparison_mode", "hybrid"))
                no_ai = bool(payload.get("no_ai", False))

                from .cli import _slug_part
                now_str = now_stamp_precise()
                browser_part = _slug_part(browser, "sdk")
                run_name = f"{now_str}_{BM.normalize_name(name)}_{browser_part}_desktop_default"
                run_dir = self.paths.runs_dir / run_name
                run_dir.mkdir(parents=True, exist_ok=True)

                current_path = run_dir / "current.png"
                current_path.write_bytes(image_bytes)

                baseline_image_path = manager.baseline_image_path(name)

                # Load saved ignore regions
                ignore_regions = []
                try:
                    meta = manager.load_metadata(name)
                    if "custom_threshold_pct" in meta:
                        threshold_pct = float(meta["custom_threshold_pct"])
                    for r in meta.get("ignore_regions", []):
                        if isinstance(r, dict):
                            ignore_regions.append((int(r["x"]), int(r["y"]), int(r["width"]), int(r["height"])))
                        elif isinstance(r, (list, tuple)) and len(r) == 4:
                            ignore_regions.append((int(r[0]), int(r[1]), int(r[2]), int(r[3])))
                except Exception:
                    pass

                result, diff_overlay, binary_diff = compare_images(
                    baseline_path=baseline_image_path,
                    current_path=current_path,
                    pixel_threshold=pixel_threshold,
                    min_region_area=min_region_area,
                    ignore_regions=ignore_regions,
                )

                baseline_for_report = _copy_baseline_into_run(baseline_image_path, run_dir)
                diff_overlay_path = run_dir / "diff_overlay.png"
                binary_diff_path = run_dir / "binary_diff.png"
                report_path = run_dir / "report.html"
                json_path = run_dir / "result.json"

                save_image(diff_overlay_path, diff_overlay)
                save_image(binary_diff_path, binary_diff)

                ai_model_path = resolve_ai_model_path(self.paths, None, no_ai)
                ai_assessment = {}
                ai_model_available = bool(ai_model_path and ai_model_path.exists())
                if ai_model_available:
                    try:
                        ai_assessment = assess_result(
                            result=result, model_path=ai_model_path,
                            baseline_image_path=baseline_image_path,
                            current_image_path=current_path,
                        ).to_dict()
                    except Exception:
                        pass

                passed, comparison_decision = decide_pass_fail(
                    comparison_mode=comparison_mode, mismatch_pct=result.mismatch_pct,
                    threshold_pct=threshold_pct, ai_assessment=ai_assessment,
                    ai_model_available=ai_model_available,
                )

                decision_obj = _initial_decision_status(passed)
                severity = summarize_severity(
                    result.mismatch_pct, len(result.regions),
                    ai_assessment.get("score"), ai_assessment.get("label"),
                )
                ai_explanation = build_ai_explanation(result, ai_assessment)

                mock_cfg = CaptureConfig(
                    name=name, url=url, browser=browser,
                    viewport=(int(payload.get("viewport_width", 1440)), int(payload.get("viewport_height", 900))),
                )
                output_payload = {
                    "case_name": name, "baseline_name": name,
                    "suite_name": payload.get("suite_name"),
                    "status": "PASS" if passed else "FAIL",
                    "threshold_pct": threshold_pct,
                    "comparison_decision": comparison_decision,
                    "ignore_regions": [list(r) for r in ignore_regions],
                    "capture": build_capture_metadata(mock_cfg),
                    "result": result.to_dict(),
                    "decision": decision_obj,
                    "ai_assessment": ai_assessment,
                    "ai_explanation": ai_explanation,
                    "severity": severity,
                }
                write_json(json_path, output_payload)
                generate_html_report(
                    report_path=report_path,
                    test_name=name,
                    baseline_image=Path("baseline.png"),
                    current_image=Path("current.png"),
                    diff_image=Path("diff_overlay.png"),
                    binary_image=Path("binary_diff.png"),
                    result=result,
                    threshold_pct=threshold_pct,
                    ignore_regions=ignore_regions,
                    capture=build_capture_metadata(mock_cfg),
                    review=decision_obj,
                    decision_history=[decision_obj],
                    ai_assessment=ai_assessment,
                    ai_explanation=ai_explanation,
                    severity=severity,
                    status=output_payload["status"],
                )
                self._invalidate_dashboard_cache()
                return self._send_json({
                    "ok": True,
                    "action": "compared",
                    "passed": passed,
                    "run_id": run_name,
                    "mismatch_pct": result.mismatch_pct,
                    "diff_pixels": result.diff_pixels,
                    "regions": len(result.regions),
                    "ai_label": ai_assessment.get("label"),
                    "severity": severity.get("label"),
                    "report_url": f"/runs/{run_name}",
                    "export_url": f"/api/runs/{run_name}/export"
                })

            return self._send_error_json("Unknown API endpoint", status=404)

        except FileNotFoundError as exc:
            return self._send_error_json(str(exc), status=404)
        except ValueError as exc:
            return self._send_error_json(str(exc), status=400)
        except json.JSONDecodeError:
            return self._send_error_json("Invalid JSON payload", status=400)
        except Exception as exc:
            return self._send_error_json(str(exc), status=500)

    def guess_type(self, path: str) -> str:  # noqa: A003
        if path.endswith(".json"):
            return "application/json"
        return mimetypes.guess_type(path)[0] or "application/octet-stream"


def serve_dashboard(project_root: Path, paths: WorkspacePaths, host: str, port: int) -> None:
    store = SqliteStore(paths.db_path)
    store.ensure_bootstrap_users()
    
    # Pre-warm AI model and Playwright browser pool asynchronously.
    # NOTE: The earlier AI-only stub (which was accidentally shadowed by this full
    # version due to Python name rebinding) has been removed.  Only one warmup
    # function now exists, covering both the model and the browser pool.
    def warmup():
        try:
            from .ai_training import _load_legacy_or_hybrid_model
            model_path = paths.models_dir / "visual_ai.pt"
            if model_path.exists():
                print("[AI Warmup] Pre-loading visual AI model in background...", flush=True)
                _load_legacy_or_hybrid_model(model_path)
                print("[AI Warmup] Visual AI model pre-loaded successfully!", flush=True)
        except Exception as e:
            print(f"[AI Warmup Warning] Failed to pre-load model: {e}", flush=True)

        try:
            get_shared_browser()
            print("[Playwright Pool] Shared browser pre-warmed successfully!", flush=True)
        except Exception as e:
            print(f"[Playwright Pool Warning] Failed to pre-warm browser: {e}", flush=True)

    import threading
    threading.Thread(target=warmup, daemon=True).start()

    # ------------------------------------------------------------------ #
    # Pre-cache git remote URL (RISK-02 fix).  This runs once synchronously
    # at startup so _github_repo_url() never needs to shell out per-request.
    # ------------------------------------------------------------------ #
    try:
        _git_proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
        )
        _GITHUB_REPO_URL_CACHE["value"] = _git_proc.stdout.strip() if _git_proc.returncode == 0 else ""
    except Exception:
        _GITHUB_REPO_URL_CACHE["value"] = ""

    # Pre-seed API key cache so the very first request doesn't pay I/O cost.
    try:
        _seed_key = IntegrationsManager(paths.root).get_config().get("api_key", "")
        with _API_KEY_LOCK:
            _API_KEY_CACHE["value"] = _seed_key
            _API_KEY_CACHE["expires_at"] = time.time() + _API_KEY_TTL
    except Exception:
        pass

    # Fix the base URL once at startup to prevent Host-header injection attacks
    # on OAuth redirect URIs (RISK-09 fix).  Always prefer the explicit host/port
    # the server is bound to; never trust the per-request Host header for this.
    _display_host = "127.0.0.1" if host in ("0.0.0.0", "", "::") else host
    _STARTUP_BASE_URL["value"] = f"http://{_display_host}:{port}"

    handler = partial(DashboardHandler, project_root=project_root, paths=paths, port=port)
    server = ThreadingHTTPServer((host, port), handler)
    print(f"Serving dashboard at http://{host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        close_shared_browser()


