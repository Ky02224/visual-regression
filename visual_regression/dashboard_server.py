from __future__ import annotations

import hmac
import socket
import json
import queue
import subprocess
import sys
import time
import uuid
import io
import os
import logging
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict
from urllib.parse import quote_plus, urlparse

import threading
from collections import defaultdict, deque

from fastapi import FastAPI, Request, Response, HTTPException, Depends, Query, UploadFile
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.concurrency import run_in_threadpool
import uvicorn
import asyncio

# Setup Logger
logger = logging.getLogger("visual_regression.dashboard_server")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


class _ThreadLocalStreamProxy:
    """Stand-in for sys.stdout/sys.stderr that captures per-thread instead of process-wide.

    contextlib.redirect_stdout mutates sys.stdout globally, which is not
    thread-safe: when multiple CLI actions run concurrently on the
    ThreadPoolExecutor below, their captured output interleaves/corrupts
    each other. Installing one of these proxies as sys.stdout/sys.stderr
    once at import time lets each worker thread register its own
    threading.local() buffer via set_buffer(); writes from other threads
    (or no registered buffer at all) fall through to the real stream.
    """

    def __init__(self, real_stream):
        self._real_stream = real_stream
        self._local = threading.local()

    def _target(self):
        return getattr(self._local, "buffer", None) or self._real_stream

    def write(self, data):
        return self._target().write(data)

    def flush(self):
        target = self._target()
        flush_fn = getattr(target, "flush", None)
        if flush_fn:
            flush_fn()

    def isatty(self):
        return False

    def __getattr__(self, name):
        return getattr(self._target(), name)

    def set_buffer(self, buf):
        self._local.buffer = buf

    def clear_buffer(self):
        self._local.buffer = None


_stdout_proxy = _ThreadLocalStreamProxy(sys.stdout)
_stderr_proxy = _ThreadLocalStreamProxy(sys.stderr)
sys.stdout = _stdout_proxy
sys.stderr = _stderr_proxy


class _thread_local_capture:
    """Context manager: capture this thread's stdout/stderr into buffers without touching other threads."""

    def __init__(self, stdout_buf, stderr_buf):
        self._stdout_buf = stdout_buf
        self._stderr_buf = stderr_buf

    def __enter__(self):
        _stdout_proxy.set_buffer(self._stdout_buf)
        _stderr_proxy.set_buffer(self._stderr_buf)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        _stdout_proxy.clear_buffer()
        _stderr_proxy.clear_buffer()
        return False


def _is_test_environment() -> bool:
    """True when running under the test suite, where CLI actions must route
    through subprocess.run (which tests patch) instead of an in-process
    cli.main() call or a real Playwright browser launch.

    tests/conftest.py sets VRT_TEST_MODE=1 explicitly for the whole test
    session; this is the primary, documented signal. The isinstance check
    is a fallback for ad-hoc `unittest.mock.patch("subprocess.run", ...)`
    use without VRT_TEST_MODE set. Previous versions of this check guessed
    from subprocess.run's class name or from "pytest" in sys.modules, which
    was both fragile (broke on mock library internals changing) and wrong
    (sys.modules stays populated for the whole pytest process, not just
    tests that actually mock anything).
    """
    if os.environ.get("VRT_TEST_MODE") == "1":
        return True
    import unittest.mock
    return isinstance(subprocess.run, unittest.mock.NonCallableMock)


_task_executor = ThreadPoolExecutor(max_workers=4)
_tasks_status: Dict[str, Dict[str, Any]] = {}
_tasks_status_lock = threading.Lock()
_MAX_TASK_HISTORY = 500

_SDK_LIMITER: Dict[str, list[float]] = defaultdict(list)
_SDK_LIMITER_LOCK = threading.Lock()
_MAX_SNAPSHOTS_PER_MINUTE = 30

_LOGIN_LIMITER: Dict[str, list[float]] = defaultdict(list)
_LOGIN_LIMITER_LOCK = threading.Lock()
_MAX_LOGIN_ATTEMPTS_PER_MINUTE = 10

_API_KEY_CACHE: Dict[str, Any] = {}
_API_KEY_TTL = 60.0
_API_KEY_LOCK = threading.Lock()

_ai_review_queue_lock = threading.Lock()
_ai_review_queue_count = 0
_ai_training_in_progress = False
_last_ai_train_time = 0.0

_SSE_SUBSCRIBERS: list[queue.Queue] = []
_SSE_SUBSCRIBERS_LOCK = threading.Lock()

def broadcast_event(event_type: str, data: dict):
    msg = {
        "type": event_type,
        "data": data,
        "timestamp": time.time(),
    }
    with _SSE_SUBSCRIBERS_LOCK:
        dead_queues = []
        for q in _SSE_SUBSCRIBERS:
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead_queues.append(q)
            except Exception:
                dead_queues.append(q)
        for dq in dead_queues:
            try:
                _SSE_SUBSCRIBERS.remove(dq)
            except ValueError:
                pass

class MetricsCollector:
    def __init__(self):
        self._lock = threading.Lock()
        self.captures_total = 0
        self.captures_failed = 0
        self.comparisons_total = 0
        self.comparisons_failed = 0
        self.ai_inferences_total = 0
        self.capture_durations = deque(maxlen=1000)
        self.compare_durations = deque(maxlen=1000)
        self.ai_durations = deque(maxlen=1000)

    def record_capture(self, duration: float, success: bool):
        with self._lock:
            self.captures_total += 1
            if not success:
                self.captures_failed += 1
            self.capture_durations.append(duration)

    def record_compare(self, duration: float, success: bool):
        with self._lock:
            self.comparisons_total += 1
            if not success:
                self.comparisons_failed += 1
            self.compare_durations.append(duration)

    def record_ai_inference(self, duration: float):
        with self._lock:
            self.ai_inferences_total += 1
            self.ai_durations.append(duration)

    def generate_prometheus_text(self, store: Any) -> str:
        try:
            baselines_count = len(store.list_baselines())
        except Exception:
            baselines_count = 0

        avg_capture = sum(self.capture_durations) / len(self.capture_durations) if self.capture_durations else 0.0
        avg_compare = sum(self.compare_durations) / len(self.compare_durations) if self.compare_durations else 0.0
        avg_ai = sum(self.ai_durations) / len(self.ai_durations) if self.ai_durations else 0.0

        return f"""# HELP vrt_baselines_total Total number of baselines
# TYPE vrt_baselines_total gauge
vrt_baselines_total {baselines_count}

# HELP vrt_captures_total Total screenshot capture attempts
# TYPE vrt_captures_total counter
vrt_captures_total {self.captures_total}

# HELP vrt_captures_failed_total Total failed screenshot capture attempts
# TYPE vrt_captures_failed_total counter
vrt_captures_failed_total {self.captures_failed}

# HELP vrt_comparisons_total Total image comparisons performed
# TYPE vrt_comparisons_total counter
vrt_comparisons_total {self.comparisons_total}

# HELP vrt_comparisons_failed_total Total failed image comparisons
# TYPE vrt_comparisons_failed_total counter
vrt_comparisons_failed_total {self.comparisons_failed}

# HELP vrt_ai_inferences_total Total AI model inferences run
# TYPE vrt_ai_inferences_total counter
vrt_ai_inferences_total {self.ai_inferences_total}

# HELP vrt_avg_capture_duration_seconds Average screenshot capture duration
# TYPE vrt_avg_capture_duration_seconds gauge
vrt_avg_capture_duration_seconds {avg_capture:.4f}

# HELP vrt_avg_compare_duration_seconds Average image comparison duration
# TYPE vrt_avg_compare_duration_seconds gauge
vrt_avg_compare_duration_seconds {avg_compare:.4f}

# HELP vrt_avg_ai_inference_duration_seconds Average AI inference duration
# TYPE vrt_avg_ai_inference_duration_seconds gauge
vrt_avg_ai_inference_duration_seconds {avg_ai:.4f}
"""

_metrics = MetricsCollector()
_GLOBAL_SCHEDULER = None
_GITHUB_REPO_URL_CACHE: Dict[str, Any] = {}
_STARTUP_BASE_URL: Dict[str, Any] = {}
_THREAD_LOCAL = threading.local()

def get_shared_browser(browser_name: str = "chromium"):
    browser_name = browser_name if browser_name in {"chromium", "firefox", "webkit"} else "chromium"
    if not hasattr(_THREAD_LOCAL, "playwright") or _THREAD_LOCAL.playwright is None:
        from playwright.sync_api import sync_playwright
        logger.info(f"[Playwright Pool] Initializing shared Playwright process on thread {threading.get_ident()}...")
        _THREAD_LOCAL.playwright = sync_playwright().start()
    if not hasattr(_THREAD_LOCAL, "browsers"):
        _THREAD_LOCAL.browsers = {}
    if browser_name not in _THREAD_LOCAL.browsers or _THREAD_LOCAL.browsers[browser_name] is None:
        logger.info(f"[Playwright Pool] Launching shared {browser_name} browser process on thread {threading.get_ident()}...")
        b_type = getattr(_THREAD_LOCAL.playwright, browser_name)
        _THREAD_LOCAL.browsers[browser_name] = b_type.launch(headless=True)
        from .browser import set_shared_browser
        set_shared_browser(_THREAD_LOCAL.playwright, _THREAD_LOCAL.browsers[browser_name])
    return _THREAD_LOCAL.playwright, _THREAD_LOCAL.browsers[browser_name]

def close_shared_browser():
    if hasattr(_THREAD_LOCAL, "browsers"):
        for _name, browser in list(_THREAD_LOCAL.browsers.items()):
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass
        _THREAD_LOCAL.browsers = {}
    if hasattr(_THREAD_LOCAL, "browser") and _THREAD_LOCAL.browser is not None:
        try:
            _THREAD_LOCAL.browser.close()
        except Exception:
            pass
        _THREAD_LOCAL.browser = None
    if hasattr(_THREAD_LOCAL, "playwright") and _THREAD_LOCAL.playwright is not None:
        try:
            _THREAD_LOCAL.playwright.stop()
        except Exception:
            pass
        _THREAD_LOCAL.playwright = None
    from .browser import set_shared_browser
    set_shared_browser(None, None)
    logger.info(f"[Playwright Pool] Shared browser processes stopped on thread {threading.get_ident()}.")

def find_selectors_for_coordinates(paths: WorkspacePaths, name: str, regions: list) -> list[str]:
    return []

def _run_background_ai_training(paths: WorkspacePaths):
    global _ai_training_in_progress, _last_ai_train_time
    try:
        from .ai_training import train_model
        logger.info("[AI Trainer] Starting background automatic training loop...")
        broadcast_event("ai_training", {"status": "started"})
        model_path = paths.models_dir / "visual_ai.pt"
        train_model(
            paths=paths,
            model_path=model_path,
            epochs=5,
            batch_size=16,
            learning_rate=1e-4,
            samples_per_image=4,
            pretrained_backbone=True
        )
        try:
            from .ai_training import export_to_onnx, compile_to_torchscript
            export_to_onnx(model_path)
            compile_to_torchscript(model_path)
        except Exception as export_err:
            logger.warning(f"[AI Trainer Warning] Failed to re-export model formats: {export_err}")
        logger.info("[AI Trainer] Background training successfully completed! Model weights updated.")
        broadcast_event("ai_training", {"status": "finished", "success": True})
    except Exception as e:
        logger.error(f"[AI Trainer Error] Background training failed: {e}")
        broadcast_event("ai_training", {"status": "finished", "success": False, "error": str(e)})
        try:
            al_dir = paths.root / "active_learning"
            last_trained_file = al_dir / ".last_trained_count"
            if last_trained_file.exists():
                last_trained_file.unlink()
        except Exception:
            pass
    finally:
        with _ai_review_queue_lock:
            _ai_training_in_progress = False
            _last_ai_train_time = time.time()

def queue_ai_training_sample(paths: WorkspacePaths):
    global _ai_training_in_progress
    al_dir = paths.root / "active_learning"
    if not al_dir.exists():
        return
    json_files = list(al_dir.glob("*.json"))
    current_count = len(json_files)
    last_trained_file = al_dir / ".last_trained_count"
    last_trained_count = 0
    if last_trained_file.exists():
        try:
            last_trained_count = int(last_trained_file.read_text(encoding="utf-8").strip())
        except Exception:
            pass
    logger.info(f"[Active Learning] Review decision saved. Current reviews: {current_count}. Last trained: {last_trained_count}.")
    if current_count - last_trained_count >= 10:
        with _ai_review_queue_lock:
            if _ai_training_in_progress:
                logger.info("[Active Learning] Background training already in progress. Skipping trigger.")
                return
            _ai_training_in_progress = True
        try:
            last_trained_file.write_text(str(current_count), encoding="utf-8")
        except Exception as e:
            logger.warning(f"[Active Learning Warning] Failed to update .last_trained_count: {e}")
        t = threading.Thread(
            target=_run_background_ai_training,
            args=(paths,),
            daemon=True
        )
        t.start()
        logger.info("[Active Learning] Triggered automatic background fine-tuning thread (reviews difference >= 10).")

from .config import WorkspacePaths, resolve_image_path
from .baseline_manager import BaselineManager
from .dashboard_data import build_dashboard_snapshot, _DashboardCache
from .review_manager import ReviewManager
from .integrations_manager import IntegrationsManager
from .database import get_store
from .github_oauth import (
    build_authorize_url,
    exchange_code_for_token,
    fetch_github_user,
    oauth_settings,
)

# FastAPI App Setup
app = FastAPI(title="The Lens Dashboard API")

# Middlewares
origins_str = os.environ.get("VRT_ALLOWED_ORIGINS", "")
allowed_origins = [o.strip() for o in origins_str.split(",") if o.strip()] if origins_str else [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8130",
    "http://127.0.0.1:8130",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"ok": False, "error": exc.detail},
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Build the message from exc.errors() rather than str(exc): the latter can
    # embed extra debug context (observed: a source file path and line number)
    # depending on FastAPI/Pydantic version and error shape, leaking server
    # filesystem layout to any client that sends a malformed request.
    messages = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()) if part != "body")
        msg = err.get("msg", "Invalid request")
        messages.append(f"{loc}: {msg}" if loc else msg)
    return JSONResponse(
        status_code=400,
        content={"ok": False, "error": "; ".join(messages) or "Invalid request"},
    )

@app.exception_handler(ValueError)
async def value_error_exception_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=400,
        content={"ok": False, "error": str(exc)},
    )

@app.exception_handler(FileNotFoundError)
async def file_not_found_exception_handler(request: Request, exc: FileNotFoundError):
    return JSONResponse(
        status_code=404,
        content={"ok": False, "error": str(exc)},
    )

# FastAPI State Dependencies
def get_paths_dep(request: Request):
    if hasattr(request.state, "paths"):
        return request.state.paths
    return getattr(app.state, "paths", None)

def get_store_dep(request: Request):
    if hasattr(request.state, "store"):
        return request.state.store
    return getattr(app.state, "store", None)

def get_project_root_dep(request: Request):
    if hasattr(request.state, "project_root"):
        return request.state.project_root
    return getattr(app.state, "project_root", None)

def get_port_dep(request: Request):
    if hasattr(request.state, "port"):
        return request.state.port
    return getattr(app.state, "port", None)

def _get_base_url_helper(port: int) -> str:
    fixed = _STARTUP_BASE_URL.get("value")
    if fixed:
        return fixed
    return f"http://127.0.0.1:{port}"

def _get_github_repo_url_helper(project_root: Path) -> str:
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

def _safe_path_helper(base: Path, relative: str) -> str:
    target = (base / relative).resolve()
    base_resolved = base.resolve()
    if base_resolved not in target.parents and target != base_resolved:
        return str(base_resolved)
    return str(target)

def _payload_to_args_helper(payload: Dict[str, Any], allowed: Dict[str, str]) -> list[str]:
    args: list[str] = []
    for key, cli_name in allowed.items():
        value = payload.get(key)
        if value is None or value == "":
            continue
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

def _run_cli_action_helper(paths, project_root, port, args: list[str]) -> Dict[str, Any]:
    from . import cli
    full_args = list(args)
    if "--root" not in full_args:
        full_args = ["--root", str(paths.root)] + full_args
    is_mocked = _is_test_environment()
    if is_mocked:
        import os
        real_root = str(project_root)
        env = dict(os.environ)
        env["PYTHONPATH"] = os.path.pathsep.join(
            [real_root] + ([env["PYTHONPATH"]] if "PYTHONPATH" in env else [])
        )
        try:
            process = subprocess.run(
                [sys.executable, "-m", "visual_regression.cli", *full_args],
                cwd=real_root,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return {
                "returncode": process.returncode,
                "stdout": process.stdout,
                "stderr": process.stderr,
            }
        except subprocess.TimeoutExpired as e:
            return {
                "returncode": 1,
                "stdout": e.stdout or "",
                "stderr": (e.stderr or "") + "\nCommand timed out after 120 seconds.",
            }
        except Exception as e:
            return {
                "returncode": 1,
                "stdout": "",
                "stderr": f"Failed to run CLI command: {e}",
            }
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    try:
        with _thread_local_capture(stdout_buf, stderr_buf):
            returncode = cli.main(full_args)
        return {
            "returncode": returncode,
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue(),
        }
    except Exception as e:
        return {
            "returncode": 1,
            "stdout": stdout_buf.getvalue(),
            "stderr": stderr_buf.getvalue() + f"\nFailed to run in-process CLI command: {e}",
        }

def _send_cli_result_helper(result: Dict[str, Any]) -> Response:
    status = 200 if result.get("returncode", 1) == 0 else 500
    payload = {"ok": result.get("returncode", 1) == 0, **result}
    if not payload["ok"] and "error" not in payload:
        payload["error"] = result.get("stderr", "").strip() or result.get("stdout", "").strip() or "Action failed."
    return JSONResponse(status_code=status, content=payload)

def _run_cli_action_async_helper(paths, project_root, port, args: list[str], use_subprocess: bool = False) -> str:
    """Run a CLI action in the background.

    ``use_subprocess`` forces a real child process instead of an in-process
    ``cli.main()`` call. This is required for ``create-multiple-baselines``:
    it uses Playwright's *async* API (for concurrent page captures), while
    every other action here (create-baseline, compare, run-suite) uses the
    *sync* API. Playwright hard-forbids mixing sync and async API usage
    within the same OS process — once any sync-API action has run in this
    server process, an in-process async capture fails with "Playwright Sync
    API inside the asyncio loop" for the remainder of the process's uptime.
    A subprocess gives the async path its own process, sidestepping the
    conflict entirely.
    """
    task_id = str(uuid.uuid4())
    is_mocked = _is_test_environment()
    if is_mocked:
        import os
        import sys
        real_root = str(project_root)
        env = dict(os.environ)
        env["PYTHONPATH"] = os.path.pathsep.join(
            [real_root] + ([env["PYTHONPATH"]] if "PYTHONPATH" in env else [])
        )
        env["VRT_DASHBOARD_PORT"] = str(port)
        full_args = list(args)
        if "--root" not in full_args:
            full_args = ["--root", str(paths.root)] + full_args
        try:
            process = subprocess.run(
                [sys.executable, "-m", "visual_regression.cli", *full_args],
                cwd=real_root,
                env=env,
                capture_output=True,
                text=True,
            )
            with _tasks_status_lock:
                _tasks_status[task_id] = {
                    "status": "completed",
                    "stdout": process.stdout,
                    "stderr": process.stderr,
                    "returncode": process.returncode,
                    "cmd": " ".join(args),
                    "created_at": time.time(),
                }
        except Exception as e:
            with _tasks_status_lock:
                _tasks_status[task_id] = {
                    "status": "failed",
                    "stderr": f"Failed mock async run: {e}",
                    "returncode": -1,
                    "cmd": " ".join(args),
                    "created_at": time.time(),
                }
        return task_id
    if use_subprocess:
        with _tasks_status_lock:
            _tasks_status[task_id] = {
                "status": "pending",
                "stdout": "",
                "stderr": "",
                "returncode": None,
                "cmd": " ".join(args),
                "created_at": time.time(),
            }
        broadcast_event("task_started", {"task_id": task_id, "cmd": " ".join(args)})
        real_root = str(project_root)
        _root = str(paths.root)

        def subprocess_job():
            import os
            import sys
            with _tasks_status_lock:
                _tasks_status[task_id]["status"] = "running"
            broadcast_event("task_progress", {"task_id": task_id, "status": "running"})
            env = dict(os.environ)
            env["PYTHONPATH"] = os.path.pathsep.join(
                [real_root] + ([env["PYTHONPATH"]] if "PYTHONPATH" in env else [])
            )
            env["VRT_DASHBOARD_PORT"] = str(port)
            full_args = list(args)
            if "--root" not in full_args:
                full_args = ["--root", _root] + full_args
            try:
                process = subprocess.run(
                    [sys.executable, "-m", "visual_regression.cli", *full_args],
                    cwd=real_root,
                    env=env,
                    capture_output=True,
                    text=True,
                )
                status_str = "completed" if process.returncode == 0 else "failed"
                with _tasks_status_lock:
                    _tasks_status[task_id].update({
                        "status": status_str,
                        "stdout": process.stdout,
                        "stderr": process.stderr,
                        "returncode": process.returncode,
                    })
                broadcast_event("task_progress", {
                    "task_id": task_id,
                    "status": status_str,
                    "returncode": process.returncode,
                })
                _DashboardCache.invalidate(paths)
            except Exception as e:
                with _tasks_status_lock:
                    _tasks_status[task_id].update({
                        "status": "failed",
                        "stderr": f"Failed to run subprocess CLI command: {e}",
                        "returncode": -1,
                    })
                broadcast_event("task_progress", {"task_id": task_id, "status": "failed", "returncode": -1})
            finally:
                with _tasks_status_lock:
                    if len(_tasks_status) > _MAX_TASK_HISTORY:
                        oldest_keys = sorted(_tasks_status, key=lambda k: _tasks_status[k].get("created_at", 0))
                        for old_key in oldest_keys[:len(_tasks_status) - _MAX_TASK_HISTORY]:
                            _tasks_status.pop(old_key, None)

        _task_executor.submit(subprocess_job)
        return task_id
    with _tasks_status_lock:
        _tasks_status[task_id] = {
            "status": "pending",
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "cmd": " ".join(args),
            "created_at": time.time(),
        }
    broadcast_event("task_started", {"task_id": task_id, "cmd": " ".join(args)})
    _root = str(paths.root)
    def job():
        with _tasks_status_lock:
            _tasks_status[task_id]["status"] = "running"
        broadcast_event("task_progress", {"task_id": task_id, "status": "running"})
        full_args = list(args)
        if "--root" not in full_args:
            full_args = ["--root", _root] + full_args
        import io
        from . import cli
        import os
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        os.environ["VRT_DASHBOARD_PORT"] = str(port)
        try:
            with _thread_local_capture(stdout_buf, stderr_buf):
                returncode = cli.main(full_args)
            status_str = "completed" if returncode == 0 else "failed"
            with _tasks_status_lock:
                _tasks_status[task_id].update({
                    "status": status_str,
                    "stdout": stdout_buf.getvalue(),
                    "stderr": stderr_buf.getvalue(),
                    "returncode": returncode
                })
            broadcast_event("task_progress", {
                "task_id": task_id,
                "status": status_str,
                "returncode": returncode
            })
            _DashboardCache.invalidate(paths)
        except (Exception, SystemExit) as e:
            with _tasks_status_lock:
                _tasks_status[task_id].update({
                    "status": "failed",
                    "stderr": stderr_buf.getvalue() + f"\nFailed to run async in-process CLI command: {e}",
                    "returncode": -1
                })
            broadcast_event("task_progress", {"task_id": task_id, "status": "failed", "returncode": -1})
        finally:
            with _tasks_status_lock:
                if len(_tasks_status) > _MAX_TASK_HISTORY:
                    oldest_keys = sorted(_tasks_status, key=lambda k: _tasks_status[k].get("created_at", 0))
                    for old_key in oldest_keys[:len(_tasks_status) - _MAX_TASK_HISTORY]:
                        _tasks_status.pop(old_key, None)
    _task_executor.submit(job)
    return task_id

# Auth dependency helpers
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

def require_dev_or_admin(request: Request, user=Depends(get_current_user), paths=Depends(get_paths_dep)):
    incoming = request.headers.get("X-Access-Key") or ""
    if incoming:
        now = time.time()
        with _API_KEY_LOCK:
            cached = _API_KEY_CACHE
            if cached.get("expires_at", 0) > now:
                secure_key = cached["value"]
            else:
                manager = IntegrationsManager(paths.root)
                secure_key = manager.get_config().get("api_key", "")
                cached["value"] = secure_key
                cached["expires_at"] = now + _API_KEY_TTL
        if secure_key and hmac.compare_digest(incoming, secure_key):
            return True
    if user and user.role in ("admin", "developer"):
        return user
    raise HTTPException(status_code=403, detail="Forbidden")

def check_authorization(request: Request, user=Depends(get_current_user), paths=Depends(get_paths_dep)):
    # Any authenticated session user (admin/developer/viewer) can view images —
    # they can already see the run/baseline metadata that links to them via
    # require_auth, which doesn't gate by role either.
    if user:
        return True
    now = time.time()
    with _API_KEY_LOCK:
        cached = _API_KEY_CACHE
        if cached.get("expires_at", 0) > now:
            secure_key = cached["value"]
        else:
            manager = IntegrationsManager(paths.root)
            secure_key = manager.get_config().get("api_key", "")
            cached["value"] = secure_key
            cached["expires_at"] = now + _API_KEY_TTL
    incoming = request.headers.get("X-Access-Key") or ""
    return bool(secure_key) and hmac.compare_digest(incoming, secure_key)

def require_authorized_client(request: Request, is_auth=Depends(check_authorization)):
    if not is_auth:
        raise HTTPException(status_code=403, detail="Forbidden")
    return True

# --- API Endpoints ---

@app.get("/api/health")
def get_health(store=Depends(get_store_dep)):
    try:
        store._execute_query("SELECT 1;", fetch=True)
        db_ok = True
    except Exception:
        db_ok = False
    return {"ok": True, "status": "healthy" if db_ok else "degraded", "db": db_ok}

@app.get("/api/tasks/status")
def get_tasks_status(id: str = Query(None), _user=Depends(require_auth)):
    if not id:
        raise HTTPException(status_code=400, detail="Missing task id")
    status = _tasks_status.get(id)
    if not status:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"ok": True, "task": status}

@app.get("/api/actions/task-status")
def get_actions_task_status(id: str = Query(None), _user=Depends(require_auth)):
    if not id:
        raise HTTPException(status_code=400, detail="Missing task id")
    status = _tasks_status.get(id)
    if not status:
        raise HTTPException(status_code=404, detail="Task not found")
    return status

@app.get("/api/auth/me")
def get_auth_me(user=Depends(get_current_user)):
    if not user:
        return {"ok": True, "authenticated": False, "user": None}
    return {
        "ok": True,
        "authenticated": True,
        "user": {"email": user.email, "role": user.role, "name": user.display_name}
    }

@app.get("/api/integrations/github/status")
def get_github_status(paths=Depends(get_paths_dep), project_root=Depends(get_project_root_dep), port=Depends(get_port_dep)):
    manager = IntegrationsManager(paths.root)
    base_url = _get_base_url_helper(port)
    settings = oauth_settings(f"{base_url}/api/integrations/github/callback")
    return {
        "configured": settings["configured"],
        "redirect_uri": settings["redirect_uri"],
        "repo_url": _get_github_repo_url_helper(project_root),
        **manager.github_status(),
    }

@app.get("/api/integrations/github/callback")
def get_github_callback(code: str = None, state: str = None, error: str = None, error_description: str = None, paths=Depends(get_paths_dep), project_root=Depends(get_project_root_dep), port=Depends(get_port_dep)):
    from fastapi.responses import RedirectResponse
    manager = IntegrationsManager(paths.root)
    if error:
        err_val = error_description or error or "Authorization failed"
        manager.log_activity(
            message=f"GitHub OAuth failed: {err_val}",
            branch="integrations",
            status="failed",
        )
        return RedirectResponse(f"/integrations?github_error={quote_plus(err_val)}")
    if not code or not state:
        return RedirectResponse("/integrations?github_error=Missing+code+or+state")
    if not manager.validate_github_state(state):
        manager.log_activity(message="GitHub OAuth failed: invalid state", branch="integrations", status="failed")
        return RedirectResponse("/integrations?github_error=Invalid+or+expired+state")
    base_url = _get_base_url_helper(port)
    settings = oauth_settings(f"{base_url}/api/integrations/github/callback")
    if not settings["configured"]:
        return RedirectResponse("/integrations?github_error=GitHub+OAuth+is+not+configured")
    token_payload = exchange_code_for_token(
        client_id=settings["client_id"],
        client_secret=settings["client_secret"],
        code=code,
        redirect_uri=settings["redirect_uri"],
    )
    if "error" in token_payload:
        err_val = token_payload.get("error_description") or token_payload.get("error") or "Unable to exchange OAuth code"
        manager.log_activity(
            message=f"GitHub OAuth failed: {err_val}",
            branch="integrations",
            status="failed",
        )
        return RedirectResponse(f"/integrations?github_error={quote_plus(err_val)}")
    access_token = token_payload.get("access_token", "")
    scopes = [scope for scope in str(token_payload.get("scope", "")).split(",") if scope]
    if not access_token:
        return RedirectResponse("/integrations?github_error=Missing+access+token")
    user = fetch_github_user(access_token)
    manager.complete_github_oauth(access_token=access_token, user=user, scopes=scopes)
    return RedirectResponse("/integrations?github=connected")

@app.get("/api/dashboard")
def get_dashboard(paths=Depends(get_paths_dep), project_root=Depends(get_project_root_dep), user=Depends(require_auth)):
    snapshot = build_dashboard_snapshot(project_root, paths)
    return snapshot

@app.get("/api/run")
def get_run(id: str = Query(None), paths=Depends(get_paths_dep), user=Depends(require_auth)):
    if not id:
        raise HTTPException(status_code=400, detail="Missing run id")
    manager = ReviewManager(paths)
    run_dir = manager.resolve_run_dir(id)
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
    return payload

@app.get("/api/active-learning/uncertain-runs")
def get_active_learning_uncertain_runs(store=Depends(get_store_dep), user=Depends(require_auth)):
    query = """
        SELECT run_id, case_name, baseline_name, status, ai_label, ai_score 
        FROM runs_index 
        WHERE decision_status IS NULL OR decision_status = 'pending' OR decision_status = ''
    """
    rows = store._execute_query(query, fetch=True)
    uncertain_runs = []
    threshold = 0.5
    for r in rows:
        score = float(r.get("ai_score") or 0.0)
        distance = abs(score - threshold)
        uncertain_runs.append({
            "run": r["run_id"],
            "case_name": r.get("case_name") or r.get("baseline_name"),
            "status": r["status"],
            "ai_label": r.get("ai_label"),
            "ai_score": score,
            "low_confidence": score > 0.0 and distance < 0.2,
            "distance": distance
        })
    uncertain_runs.sort(key=lambda x: x["distance"])
    return {"ok": True, "runs": uncertain_runs[:20]}

@app.get("/api/baseline")
def get_baseline(id: str = Query(None), paths=Depends(get_paths_dep), user=Depends(require_auth)):
    if not id:
        raise HTTPException(status_code=400, detail="Missing baseline id")
    manager = BaselineManager(paths)
    payload = manager.get_baseline_details(id)
    return payload

@app.get("/api/ai-suggestions")
def get_ai_suggestions(baseline_name: str = Query(None), run_id: str = Query(None), store=Depends(get_store_dep), paths=Depends(get_paths_dep), user=Depends(require_auth)):
    if not baseline_name or not run_id:
        raise HTTPException(status_code=400, detail="Missing baseline_name or run_id parameters")
    from .ai_auto_ignore import get_auto_ignore_suggestions
    suggestions = get_auto_ignore_suggestions(store, paths, baseline_name, run_id)
    return {"ok": True, "suggestions": suggestions}

@app.get("/api/comments")
def get_comments(run_id: str = Query(None), store=Depends(get_store_dep), user=Depends(require_auth)):
    if not run_id:
        raise HTTPException(status_code=400, detail="Missing run_id parameter")
    comments = store.list_comments(run_id)
    return {"ok": True, "comments": comments}

@app.get("/api/integrations")
def get_integrations(paths=Depends(get_paths_dep), port=Depends(get_port_dep), user=Depends(require_auth)):
    manager = IntegrationsManager(paths.root)
    config = manager.get_config()
    token = config.get("api_key", "")
    masked_token = (token[:7] + "*" * 20) if len(token) > 10 else "********"
    webhook_url = config.get("webhook_url", "")
    base_url = _get_base_url_helper(port)
    settings = oauth_settings(f"{base_url}/api/integrations/github/callback")
    return {
        # A Slack/Discord/Teams webhook URL *is* its own bearer credential —
        # anyone holding it can post as the integration — so it gets the same
        # admin-only treatment as the API key, not returned to viewer/developer.
        "webhook_url": webhook_url if user.role == "admin" else "",
        "webhook_threshold": config.get("webhook_threshold", 1.0),
        "api_key": masked_token,
        "webhook_connected": bool(webhook_url),
        "activity_count": len(config.get("activity", [])),
        "github_configured": settings["configured"],
    }

@app.get("/api/audit")
def get_audit(limit: int = Query(200), store=Depends(get_store_dep), user=Depends(require_admin)):
    limit = max(1, min(limit, 1000))
    logs = store.get_audit_logs(limit=limit)
    return {"logs": logs}

@app.get("/api/integrations/activity")
def get_integrations_activity(paths=Depends(get_paths_dep), user=Depends(require_auth)):
    manager = IntegrationsManager(paths.root)
    config = manager.get_config()
    return {"activity": config.get("activity", [])}

@app.get("/api/users")
def get_users(store=Depends(get_store_dep), user=Depends(require_admin)):
    users = store.list_users()
    return {"ok": True, "users": users}

@app.get("/api/runs/{run_id}/export")
def get_run_export(run_id: str, paths=Depends(get_paths_dep), user=Depends(require_auth)):
    if not run_id or "/" in run_id or ".." in run_id:
        raise HTTPException(status_code=400, detail="Invalid run id")
    run_dir = paths.runs_dir / run_id
    if not run_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    from .export_report import generate_standalone_report
    html_content = generate_standalone_report(run_dir)
    html_bytes = html_content.encode("utf-8")
    safe_name = run_id[:64].replace("/", "_").replace("\\", "_")
    return Response(
        content=html_bytes,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="report-{safe_name}.html"'}
    )

@app.get("/api/events/stream")
def get_events_stream(_user=Depends(require_auth)):
    q = queue.Queue(maxsize=100)
    with _SSE_SUBSCRIBERS_LOCK:
        if len(_SSE_SUBSCRIBERS) < 50:
            _SSE_SUBSCRIBERS.append(q)
        else:
            try:
                _SSE_SUBSCRIBERS.pop(0)
            except IndexError:
                pass
            _SSE_SUBSCRIBERS.append(q)

    async def event_generator():
        try:
            yield "event: ping\ndata: {}\n\n"
            last_ping = time.time()
            while True:
                try:
                    while not q.empty():
                        msg = q.get_nowait()
                        yield f"event: {msg['type']}\ndata: {json.dumps(msg['data'])}\n\n"
                except queue.Empty:
                    pass
                if time.time() - last_ping > 15.0:
                    yield "event: ping\ndata: {}\n\n"
                    last_ping = time.time()
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        finally:
            with _SSE_SUBSCRIBERS_LOCK:
                if q in _SSE_SUBSCRIBERS:
                    _SSE_SUBSCRIBERS.remove(q)
                    
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/scheduler/jobs")
def get_scheduler_jobs(user=Depends(require_auth)):
    if not _GLOBAL_SCHEDULER:
        return {"ok": False, "jobs": []}
    jobs = _GLOBAL_SCHEDULER.list_jobs()
    from dataclasses import asdict
    return {"ok": True, "jobs": [asdict(j) for j in jobs]}

@app.post("/api/scheduler/jobs")
def post_scheduler_jobs(payload: dict, project_root=Depends(get_project_root_dep), user=Depends(require_dev_or_admin)):
    name = payload.get("name")
    cron_expression = payload.get("cron_expression")
    suite_path = payload.get("suite_path")
    if not name or not cron_expression or not suite_path:
        raise HTTPException(status_code=400, detail="Missing required fields")
    if not _GLOBAL_SCHEDULER:
        raise HTTPException(status_code=500, detail="Scheduler not initialized")

    suite_path = str(suite_path).strip()
    if not suite_path.lower().endswith((".yaml", ".yml")):
        raise HTTPException(status_code=400, detail="suite_path must be a .yaml/.yml file")
    resolved_suite_path = Path(_safe_path_helper(project_root, suite_path))
    if not resolved_suite_path.is_file():
        raise HTTPException(status_code=400, detail=f"Suite file not found: {suite_path}")
    # Store as a path relative to project_root, matching what the scheduler's
    # subprocess (run with project_root as its cwd) will resolve.
    safe_suite_path = str(resolved_suite_path.relative_to(project_root.resolve()))

    job_id = _GLOBAL_SCHEDULER.add_job(name, cron_expression, safe_suite_path)
    broadcast_event("scheduler_updated", {"action": "add", "job_id": job_id})
    return {"ok": True, "job_id": job_id}

@app.post("/api/scheduler/jobs/delete")
def post_scheduler_jobs_delete(payload: dict, user=Depends(require_dev_or_admin)):
    job_id = payload.get("job_id")
    if not job_id:
        raise HTTPException(status_code=400, detail="Missing job_id")
    if not _GLOBAL_SCHEDULER:
        raise HTTPException(status_code=500, detail="Scheduler not initialized")
    success = _GLOBAL_SCHEDULER.remove_job(job_id)
    broadcast_event("scheduler_updated", {"action": "delete", "job_id": job_id})
    return {"ok": success}

@app.post("/api/scheduler/jobs/toggle")
def post_scheduler_jobs_toggle(payload: dict, user=Depends(require_dev_or_admin)):
    job_id = payload.get("job_id")
    enabled = bool(payload.get("enabled", True))
    if not job_id:
        raise HTTPException(status_code=400, detail="Missing job_id")
    if not _GLOBAL_SCHEDULER:
        raise HTTPException(status_code=500, detail="Scheduler not initialized")
    success = _GLOBAL_SCHEDULER.enable_job(job_id, enabled)
    broadcast_event("scheduler_updated", {"action": "toggle", "job_id": job_id, "enabled": enabled})
    return {"ok": success}

@app.post("/api/events/emit")
def post_events_emit(payload: dict, user=Depends(require_dev_or_admin)):
    event_type = payload.get("type")
    data = payload.get("data", {})
    if not event_type:
        raise HTTPException(status_code=400, detail="Missing event type")
    broadcast_event(event_type, data)
    return {"ok": True}

@app.post("/api/runs/upload")
async def post_runs_upload(request: Request, paths=Depends(get_paths_dep), project_root=Depends(get_project_root_dep), port=Depends(get_port_dep), store=Depends(get_store_dep), authorized=Depends(require_dev_or_admin)):
    content_length = int(request.headers.get("Content-Length", 0))
    if content_length > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Upload too large (max 50MB)")
    form = await request.form()
    parts = {}
    for key in form.keys():
        val = form[key]
        if isinstance(val, UploadFile):
            content = await val.read()
            parts[key] = {
                "filename": val.filename,
                "content": content,
                "content_type": val.content_type
            }
        else:
            parts[key] = str(val)
    from .server_services import handle_run_upload
    try:
        res = await run_in_threadpool(
            handle_run_upload,
            paths=paths,
            project_root=project_root,
            parts=parts,
            github_repo_url=_get_github_repo_url_helper(project_root),
            dashboard_base_url=_get_base_url_helper(port),
            store=store,
        )
        _DashboardCache.invalidate(paths)
        return res
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.post("/api/auth/login")
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
            raise HTTPException(status_code=429, detail="Too many login attempts. Please wait a minute before trying again.")
        recent.append(now_ts)
        _LOGIN_LIMITER[client_ip] = recent
    user = store.authenticate(email, password)
    if not user:
        store.audit(None, None, "auth.login_failed", {"email": email})
        raise HTTPException(status_code=401, detail="Invalid credentials")
    with _LOGIN_LIMITER_LOCK:
        _LOGIN_LIMITER.pop(client_ip, None)
    old_token = request.cookies.get("lens_session")
    if old_token:
        store.delete_session(old_token)
    token = store.create_session(user.email, ttl_seconds=60 * 60 * 12)
    response.set_cookie(
        key="lens_session",
        value=token,
        path="/",
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 12,
        secure=os.environ.get("LENS_SECURE_COOKIES") == "true",
    )
    store.audit(user.email, user.role, "auth.login", {"email": user.email})
    return {"ok": True, "user": {"email": user.email, "role": user.role}}

@app.post("/api/auth/logout")
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
        secure=os.environ.get("LENS_SECURE_COOKIES") == "true",
    )
    return {"ok": True}

@app.post("/api/bulk-review")
def post_bulk_review(payload: dict, paths=Depends(get_paths_dep), store=Depends(get_store_dep), user=Depends(require_admin)):
    run_refs = payload.get("runs", [])
    decision_value = str(payload.get("decision", "")).strip()
    decider = user.email if user else str(payload.get("reviewer", "") or payload.get("decider", "")).strip()
    if not run_refs or not isinstance(run_refs, list):
        raise HTTPException(status_code=400, detail="Missing or invalid runs list")
    if decision_value not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Decision must be approved or rejected")
    if not decider:
        raise HTTPException(status_code=400, detail="Decider is required")
    manager = ReviewManager(paths)
    results = []
    reviewed_payloads = []
    for run_ref in run_refs:
        try:
            run_dir = manager.resolve_run_dir(str(run_ref))
            # Called for the write it performs; the payload is re-read below.
            manager.save_decision(
                run_dir=run_dir,
                decision=decision_value,
                decider=decider,
                comment=str(payload.get("comment", "")),
            )
            try:
                loaded_payload = manager.load_run_payload(run_dir)
                # result.json has no "run"/"run_id" key of its own — without this,
                # bulk_insert_runs filters the row out entirely (empty run_id).
                loaded_payload["run_id"] = run_dir.name
                reviewed_payloads.append(loaded_payload)
            except Exception as db_err:
                logger.warning(f"Failed to load run payload for bulk index update: {db_err}")
            results.append({"run": run_ref, "success": True})
        except Exception as e:
            results.append({"run": run_ref, "success": False, "error": str(e)})
    if reviewed_payloads:
        try:
            store.bulk_insert_runs(reviewed_payloads)
        except Exception as db_err:
            logger.warning(f"Failed to bulk upsert run index on bulk review: {db_err}")
    _DashboardCache.invalidate(paths)
    queue_ai_training_sample(paths)
    return {"ok": True, "results": results}

@app.post("/api/review")
@app.post("/api/decision")
@app.post("/api/actions/review")
def post_review(payload: dict, paths=Depends(get_paths_dep), store=Depends(get_store_dep), port=Depends(get_port_dep), user=Depends(require_admin)):
    run_ref = str(payload.get("run", "")).strip()
    decision_value = str(payload.get("decision", "")).strip()
    decider = user.email if user else str(payload.get("reviewer", "") or payload.get("decider", "")).strip()
    if not run_ref:
        raise HTTPException(status_code=400, detail="Missing run id")
    if decision_value not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Decision must be approved or rejected")
    if not decider:
        raise HTTPException(status_code=400, detail="Decider is required")
    manager = ReviewManager(paths)
    run_dir = manager.resolve_run_dir(run_ref)
    decision = manager.save_decision(
        run_dir=run_dir,
        decision=decision_value,
        decider=decider,
        comment=str(payload.get("comment", "")),
    )
    try:
        run_payload = manager.load_run_payload(run_dir)
        # result.json has no "run"/"run_id" key of its own — without this,
        # upsert_run_index can't resolve a run_id and silently no-ops,
        # leaving the dashboard's DB index stale after every review action.
        run_payload["run_id"] = run_dir.name
        store.upsert_run_index(run_payload)
    except Exception as e:
        logger.warning(f"Failed to upsert run index on review: {e}")
    try:
        run_payload = manager.load_run_payload(run_dir)
        build_id = run_payload.get("build_id")
        if build_id:
            build_dir = paths.builds_dir / build_id
            build_json_file = build_dir / "build.json"
            if build_json_file.exists():
                build_meta = json.loads(build_json_file.read_text(encoding="utf-8"))
                commit_sha = build_meta.get("commit_sha")
                if commit_sha:
                    all_runs = []
                    for r_dir in paths.runs_dir.iterdir():
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
                    failed_any = False
                    for r_payload in all_runs:
                        status = r_payload.get("status")
                        dec_status = (r_payload.get("decision") or {}).get("status")
                        if status == "FAIL" and dec_status != "approved":
                            failed_any = True
                            break
                    state = "failure" if failed_any else "success"
                    description = "Visual check: All snapshots approved/passed" if not failed_any else "Visual check: Remaining unapproved mismatches"
                    integrations_manager = IntegrationsManager(paths.root)
                    github_config = integrations_manager.get_config().get("github", {})
                    if github_config.get("connected"):
                        repo_url = _get_github_repo_url_helper(paths.root.parent)
                        if repo_url:
                            from urllib.parse import quote
                            base_url = _get_base_url_helper(port)
                            target_url = f"{base_url}/build/{quote(build_id)}"
                            integrations_manager.post_github_commit_status(
                                repo_url=repo_url,
                                sha=commit_sha,
                                state=state,
                                target_url=target_url,
                                description=description
                            )
    except Exception as e:
        logger.warning(f"Failed to post GitHub status update: {e}")
    store.audit(
        user.email if user else decider,
        user.role if user else None,
        f"decision.{decision_value}",
        {"run": run_ref, "decider": decider, "comment": str(payload.get("comment", ""))},
    )
    _DashboardCache.invalidate(paths)
    queue_ai_training_sample(paths)
    return {"ok": True, "decision": decision}

@app.post("/api/run/delete")
def post_run_delete(payload: dict, paths=Depends(get_paths_dep), user=Depends(require_admin)):
    run_ref = str(payload.get("run", "")).strip()
    if not run_ref:
        raise HTTPException(status_code=400, detail="Missing run id")
    manager = ReviewManager(paths)
    result = manager.delete_run(run_ref)
    _DashboardCache.invalidate(paths)
    return {"ok": True, **result}

@app.post("/api/baseline/update-threshold")
def post_baseline_update_threshold(payload: dict, paths=Depends(get_paths_dep), user=Depends(require_dev_or_admin)):
    name = str(payload.get("name", "")).strip()
    threshold_val = payload.get("threshold_pct")
    if not name:
        raise HTTPException(status_code=400, detail="Missing baseline name")
    manager = BaselineManager(paths)
    try:
        if threshold_val is None or str(threshold_val).strip() == "":
            manager.save_custom_threshold(name, None)
        else:
            manager.save_custom_threshold(name, float(threshold_val))
        _DashboardCache.invalidate(paths)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/baseline/delete")
def post_baseline_delete(payload: dict, paths=Depends(get_paths_dep), user=Depends(require_admin)):
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Missing baseline name")
    manager = BaselineManager(paths)
    result = manager.delete_baseline(name)
    _DashboardCache.invalidate(paths)
    return {"ok": True, **result}

@app.post("/api/baseline/restore")
def post_baseline_restore(payload: dict, paths=Depends(get_paths_dep), user=Depends(require_admin)):
    name = str(payload.get("name", "")).strip()
    version = str(payload.get("version", "")).strip()
    if not name or not version:
        raise HTTPException(status_code=400, detail="Baseline name and version are required")
    manager = BaselineManager(paths)
    result = manager.restore_version(
        name=name,
        version=version,
        restored_by=str(payload.get("restored_by", "")) or None,
    )
    _DashboardCache.invalidate(paths)
    return {"ok": True, **result}

@app.post("/api/ignore-regions")
def post_ignore_regions(payload: dict, paths=Depends(get_paths_dep), project_root=Depends(get_project_root_dep), port=Depends(get_port_dep), store=Depends(get_store_dep), user=Depends(require_admin)):
    name = str(payload.get("name", "")).strip()
    run_id = str(payload.get("run_id", "")).strip()
    ignore_regions = payload.get("ignore_regions", [])
    if not name:
        raise HTTPException(status_code=400, detail="Missing baseline name")
    from .server_services import handle_ignore_regions_update
    try:
        res = handle_ignore_regions_update(
            paths=paths,
            name=name,
            run_id=run_id,
            ignore_regions=ignore_regions,
            find_selectors_fn=find_selectors_for_coordinates,
            github_repo_url=_get_github_repo_url_helper(project_root),
            dashboard_base_url=_get_base_url_helper(port),
            store=store,
        )
        _DashboardCache.invalidate(paths)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/comments/create")
def post_comments_create(payload: dict, store=Depends(get_store_dep), user=Depends(get_current_user), authorized=Depends(require_authorized_client)):
    run_id = str(payload.get("run_id", "")).strip()
    x_pct = float(payload.get("x_pct", 0.0))
    y_pct = float(payload.get("y_pct", 0.0))
    content = str(payload.get("content", "")).strip()
    if not run_id or not content:
        raise HTTPException(status_code=400, detail="run_id and content are required")
    author = user.email if user else ("automation-api" if authorized else "anonymous")
    comment_id = f"comment-{uuid.uuid4()}"
    store.add_comment(comment_id, run_id, x_pct, y_pct, author, content)
    broadcast_event("comment_updated", {"run_id": run_id, "action": "create", "comment_id": comment_id})
    return {"ok": True, "comment_id": comment_id}

@app.post("/api/comments/delete")
def post_comments_delete(payload: dict, store=Depends(get_store_dep), user=Depends(get_current_user), authorized=Depends(require_authorized_client)):
    comment_id = str(payload.get("comment_id", "")).strip()
    if not comment_id:
        raise HTTPException(status_code=400, detail="comment_id is required")
    author = None
    if hasattr(store, "pool"):
        rows = store._execute_query("SELECT author FROM comments WHERE id = %s;", (comment_id,), fetch=True)
        if rows:
            author = rows[0]["author"]
    else:
        with store._connect() as conn:
            row = conn.execute("SELECT author FROM comments WHERE id = ?;", (comment_id,)).fetchone()
            if row:
                author = row["author"]
    is_admin = user and user.role == "admin"
    is_author = user and user.email == author
    if not is_admin and not is_author and not authorized:
        raise HTTPException(status_code=403, detail="Forbidden")
    run_id = None
    if hasattr(store, "pool"):
        rows = store._execute_query("SELECT run_id FROM comments WHERE id = %s;", (comment_id,), fetch=True)
        if rows:
            run_id = rows[0]["run_id"]
    else:
        with store._connect() as conn:
            row = conn.execute("SELECT run_id FROM comments WHERE id = ?;", (comment_id,)).fetchone()
            if row:
                run_id = row["run_id"]
    store.delete_comment(comment_id)
    if run_id:
        broadcast_event("comment_updated", {"run_id": run_id, "action": "delete", "comment_id": comment_id})
    return {"ok": True}

@app.post("/api/ignore-css-selectors")
def post_ignore_css_selectors(payload: dict, user=Depends(require_dev_or_admin)):
    return {"ok": True, "ignore_css_selectors": []}

@app.post("/api/actions/create-demo-baselines")
def post_actions_create_demo_baselines(paths=Depends(get_paths_dep), project_root=Depends(get_project_root_dep), port=Depends(get_port_dep), authorized=Depends(require_dev_or_admin)):
    result = _run_cli_action_helper(paths, project_root, port, ["create-suite-baselines", "--suite", "suite.demo.yaml", "--overwrite"])
    _DashboardCache.invalidate(paths)
    return _send_cli_result_helper(result)

@app.post("/api/actions/train-ai")
def post_actions_train_ai(paths=Depends(get_paths_dep), project_root=Depends(get_project_root_dep), port=Depends(get_port_dep), authorized=Depends(require_dev_or_admin)):
    result = _run_cli_action_helper(paths, project_root, port, ["train-ai", "--epochs", "20", "--samples-per-image", "12"])
    _DashboardCache.invalidate(paths)
    return _send_cli_result_helper(result)

@app.post("/api/actions/compare-defect")
def post_actions_compare_defect(paths=Depends(get_paths_dep), project_root=Depends(get_project_root_dep), port=Depends(get_port_dep), authorized=Depends(require_dev_or_admin)):
    demo_base = os.environ.get("DEMO_BASE_URL", f"http://127.0.0.1:{port}").rstrip("/")
    defect_url = f"{demo_base}/demo/index.html?lang=en-US&defect=missing-cta"
    result = _run_cli_action_helper(paths, project_root, port, ["compare", "--name", "demo-home-en", "--url", defect_url])
    _DashboardCache.invalidate(paths)
    return _send_cli_result_helper(result)

@app.post("/api/actions/create-baseline")
def post_actions_create_baseline(payload: dict, paths=Depends(get_paths_dep), project_root=Depends(get_project_root_dep), port=Depends(get_port_dep), authorized=Depends(require_dev_or_admin)):
    args = ["create-baseline", "--name", str(payload.get("name", ""))]
    args.extend(
        _payload_to_args_helper(
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
                "login_url": "--login-url",
                "login_username": "--login-username",
                "login_password": "--login-password",
                "username_selector": "--username-selector",
                "password_selector": "--password-selector",
                "submit_selector": "--submit-selector",
            },
        )
    )
    result = _run_cli_action_helper(paths, project_root, port, args)
    _DashboardCache.invalidate(paths)
    return _send_cli_result_helper(result)

@app.post("/api/actions/create-multiple-baselines")
@app.post("/api/actions/crawl-baseline")
def post_actions_crawl_baseline(payload: dict, paths=Depends(get_paths_dep), project_root=Depends(get_project_root_dep), port=Depends(get_port_dep), authorized=Depends(require_dev_or_admin)):
    args = [
        "create-multiple-baselines",
        "--url",
        str(payload.get("url", "")),
        "--page-limit",
        str(payload.get("page_limit", 30)),
    ]
    args.extend(
        _payload_to_args_helper(
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
                "login_url": "--login-url",
                "login_username": "--login-username",
                "login_password": "--login-password",
                "username_selector": "--username-selector",
                "password_selector": "--password-selector",
                "submit_selector": "--submit-selector",
                "concurrency": "--concurrency",
            },
        )
    )
    if payload.get("preserve_query"):
        args.append("--preserve-query")
    if payload.get("overwrite"):
        args.append("--overwrite")
    if payload.get("fail_fast"):
        args.append("--fail-fast")
    task_id = _run_cli_action_async_helper(paths, project_root, port, args, use_subprocess=True)
    return {"ok": True, "task_id": task_id, "message": "Multiple capture started in the background. Check the task status for progress."}

@app.post("/api/actions/update-baseline")
def post_actions_update_baseline(payload: dict, paths=Depends(get_paths_dep), project_root=Depends(get_project_root_dep), port=Depends(get_port_dep), user=Depends(require_admin)):
    old_name = payload.get("old")
    new_name = payload.get("new")
    if old_name and new_name:
        new_image_path = resolve_image_path(paths.baselines_dir / new_name, "baseline")
        args = ["update-baseline", "--name", str(old_name), "--image", str(new_image_path)]
        updated_by = payload.get("updated_by")
        if not updated_by and user:
            updated_by = user.email
        if updated_by:
            args.extend(["--updated-by", str(updated_by)])
    else:
        args = ["update-baseline", "--name", str(payload.get("name", ""))]
        args.extend(
            _payload_to_args_helper(
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
                    "login_url": "--login-url",
                    "login_username": "--login-username",
                    "login_password": "--login-password",
                    "username_selector": "--username-selector",
                    "password_selector": "--password-selector",
                    "submit_selector": "--submit-selector",
                },
            )
        )
    result = _run_cli_action_helper(paths, project_root, port, args)
    _DashboardCache.invalidate(paths)
    return _send_cli_result_helper(result)

def _dispatch_compare_matrix(payload: dict, paths, project_root, port) -> Dict[str, Any]:
    """Build compare-matrix CLI args from a multi-browser/device/locale payload and dispatch it."""
    browsers = payload.get("browsers") or []
    devices = payload.get("devices") or []
    locales = payload.get("locales") or []
    args = ["compare-matrix", "--name", str(payload.get("name", ""))]
    if payload.get("url"):
        args.extend(["--url", str(payload.get("url"))])
    for browser in browsers:
        b_val = str(browser).strip().lower()
        if b_val == "chrome":
            b_val = "chromium"
        elif b_val == "safari":
            b_val = "webkit"
        args.extend(["--browser", b_val])
    for device in devices:
        d_val = str(device).strip()
        if d_val.lower() == "desktop":
            continue
        args.extend(["--device", d_val])
    for locale in locales:
        args.extend(["--locale", str(locale)])
    args.extend(
        _payload_to_args_helper(
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
                "login_url": "--login-url",
                "login_username": "--login-username",
                "login_password": "--login-password",
                "username_selector": "--username-selector",
                "password_selector": "--password-selector",
                "submit_selector": "--submit-selector",
            },
        )
    )
    if payload.get("no_ai"):
        args.append("--no-ai")
    if payload.get("fail_fast"):
        args.append("--fail-fast")
    result = _run_cli_action_helper(paths, project_root, port, args)
    _DashboardCache.invalidate(paths)
    return _send_cli_result_helper(result)


def _dispatch_compare_via_subprocess(payload: dict, effective_payload: dict, name: str, paths, project_root, port) -> Dict[str, Any]:
    """Build single-case compare CLI args and dispatch via subprocess (test-environment path)."""
    args = ["compare", "--name", name]
    args.extend(
        _payload_to_args_helper(
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
                "login_url": "--login-url",
                "login_username": "--login-username",
                "login_password": "--login-password",
                "username_selector": "--username-selector",
                "password_selector": "--password-selector",
                "submit_selector": "--submit-selector",
            },
        )
    )
    if payload.get("no_ai"):
        args.append("--no-ai")
    result = _run_cli_action_helper(paths, project_root, port, args)
    _DashboardCache.invalidate(paths)
    return _send_cli_result_helper(result)


@app.post("/api/actions/compare")
def post_actions_compare(payload: dict, paths=Depends(get_paths_dep), project_root=Depends(get_project_root_dep), port=Depends(get_port_dep), store=Depends(get_store_dep), user=Depends(require_dev_or_admin)):
    browsers = payload.get("browsers") or []
    devices = payload.get("devices") or []
    locales = payload.get("locales") or []
    if any((len(browsers) > 1, len(devices) > 1, len(locales) > 1)):
        return _dispatch_compare_matrix(payload, paths, project_root, port)
    effective_payload = dict(payload)
    if browsers:
        effective_payload["browser"] = browsers[0]
    if devices:
        effective_payload["device"] = "" if str(devices[0]).strip().lower() == "desktop" else devices[0]
    if locales:
        effective_payload["locale"] = locales[0]
    name = str(effective_payload.get("name", "")).strip()
    url = str(effective_payload.get("url", "")).strip()
    is_mocked = _is_test_environment()
    if is_mocked:
        return _dispatch_compare_via_subprocess(payload, effective_payload, name, paths, project_root, port)
    from .cli import _run_compare, resolve_ai_model_path
    from .config import CaptureConfig
    manager = BaselineManager(paths)
    if not manager.exists(name):
        raise HTTPException(status_code=404, detail=f"Baseline '{name}' does not exist.")
    if not url:
        url = manager.load_metadata(name).get("capture", {}).get("url")
    if not url:
        raise HTTPException(status_code=400, detail="Compare requires a URL.")
    baseline_capture = manager.load_metadata(name).get("capture", {})
    login_url = effective_payload.get("login_url") or baseline_capture.get("login_url")
    login_username = effective_payload.get("login_username") or baseline_capture.get("login_username")
    login_password = effective_payload.get("login_password") or baseline_capture.get("login_password")
    username_selector = effective_payload.get("username_selector") or baseline_capture.get("username_selector")
    password_selector = effective_payload.get("password_selector") or baseline_capture.get("password_selector")
    submit_selector = effective_payload.get("submit_selector") or baseline_capture.get("submit_selector")
    viewport_str = str(effective_payload.get("viewport") or "1440x900")
    if "x" in viewport_str:
        w, h = viewport_str.split("x", 1)
        viewport_val = (int(w), int(h))
    else:
        viewport_val = (1440, 900)
    capture_cfg = CaptureConfig(
        name=name, url=url, browser=str(effective_payload.get("browser", "chromium")),
        device=effective_payload.get("device") or None, viewport=viewport_val,
        wait_ms=int(effective_payload.get("wait_ms", 0)), wait_until=str(effective_payload.get("wait_until", "load")),
        navigation_timeout_ms=int(effective_payload.get("timeout_ms", 45000)),
        full_page=not bool(effective_payload.get("no_full_page", False)),
        disable_animations=not bool(effective_payload.get("allow_animations", False)),
        locale=effective_payload.get("locale") or None, timezone_id=effective_payload.get("timezone_id") or None,
        color_scheme=effective_payload.get("color_scheme", "light"), login_url=login_url or None,
        login_username=login_username or None, login_password=login_password or None,
        username_selector=username_selector or None, password_selector=password_selector or None,
        submit_selector=submit_selector or None,
    )
    try:
        start_time = time.time()
        def run_in_pool():
            req_browser = str(effective_payload.get("browser", "chromium"))
            playwright_inst, browser_inst = get_shared_browser(req_browser)
            ai_model_path = resolve_ai_model_path(paths, None, bool(effective_payload.get("no_ai", False)))
            return _run_compare(
                manager=manager, paths=paths, case_name=name, capture_cfg=capture_cfg,
                threshold_pct=float(effective_payload.get("threshold_pct", 0.5)),
                pixel_threshold=int(effective_payload.get("pixel_threshold", 20)),
                min_region_area=int(effective_payload.get("min_region_area", 120)),
                ignore_regions=[], ai_model_path=ai_model_path, suite_name=None,
                comparison_mode=str(effective_payload.get("comparison_mode", "hybrid")),
                playwright_instance=playwright_inst, browser_instance=browser_inst,
            )
        future = _task_executor.submit(run_in_pool)
        passed, current_img_path, details = future.result(timeout=60.0)
        duration = time.time() - start_time
        _metrics.record_compare(duration, success=True)
        broadcast_event("compare_completed", {"name": name, "passed": passed, "duration": duration})
        _DashboardCache.invalidate(paths)
        run_id = current_img_path.parent.name
        return {
            "ok": True, "returncode": 0 if passed else 2, "message": f"Comparison completed. Passed: {passed}",
            "run_id": run_id, "passed": passed, "mismatch_pct": details.get("mismatch_pct", 0.0),
            "ai_explanation": details.get("ai_explanation", ""),
        }
    except Exception as exc:
        duration = time.time() - start_time
        _metrics.record_compare(duration, success=False)
        broadcast_event("compare_failed", {"name": name, "error": str(exc)})
        try:
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            run_id = f"{name}_{timestamp}_error"
            run_dir = paths.runs_dir / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            err_payload = {
                "case_name": name, "baseline_name": name, "suite_name": None, "status": "FAIL",
                "error": str(exc), "created_at": int(time.time()),
                "threshold_pct": float(effective_payload.get("threshold_pct", 0.5)),
                "capture": {
                    "browser": effective_payload.get("browser", "chromium"),
                    "device": effective_payload.get("device", "desktop"), "locale": effective_payload.get("locale", ""),
                    "url": effective_payload.get("url", ""),
                },
                "result": {
                    "baseline_size": [0, 0], "current_size": [0, 0], "diff_pixels": 0,
                    "total_pixels": 0, "mismatch_pct": 1.0, "ssim_score": 0.0, "regions": []
                },
                "decision": {
                    "status": "error", "reviewer": "System", "comment": f"Comparison execution crashed: {exc}",
                    "timestamp": datetime.datetime.now().isoformat()
                },
                "severity": { "score": 100.0, "label": "high" },
                "ai_assessment": {
                    "score": 0.0, "label": "error", "threshold": 0.5, "model_name": "none",
                    "meaningful_change": True, "calibrated_score": 0.0, "low_confidence": False,
                    "ai_explanation": f"Execution crashed with error: {exc}"
                }
            }
            from .reporter import write_json
            write_json(run_dir / "result.json", err_payload)
            run_payload = {
                "run_id": run_id, "case_name": name, "baseline_name": name, "suite_name": None,
                "status": "FAIL", "mismatch_pct": 1.0, "diff_regions": 0, "decision_status": "error",
                "decided_at": datetime.datetime.now().isoformat(), "severity_label": "high", "ai_label": "error",
                "browser": effective_payload.get("browser", "chromium"), "device": effective_payload.get("device", "desktop"),
                "locale": effective_payload.get("locale", ""), "url": effective_payload.get("url", ""),
                "report_href": f"/artifacts/{run_id}/report.html", "decider": "System",
                "decision_comment": f"Execution Error: {exc}", "ai_score": 0.0,
            }
            store.upsert_run_index(run_payload)
            _DashboardCache.invalidate(paths)
        except Exception as archive_err:
            logger.warning(f"Failed to log failure run: {archive_err}")
        raise HTTPException(status_code=500, detail=str(exc))

@app.post("/api/actions/compare-multiple")
def post_actions_compare_multiple(payload: dict, paths=Depends(get_paths_dep), project_root=Depends(get_project_root_dep), port=Depends(get_port_dep), user=Depends(require_dev_or_admin)):
    """Batch-compare many baselines in one background task.

    Builds an in-memory suite (one test case per baseline, using each
    baseline's own stored capture settings) and dispatches it via the same
    run-suite/background-task infrastructure used elsewhere, rather than
    looping over /api/actions/compare synchronously.
    """
    raw_names = payload.get("names") or []
    if not isinstance(raw_names, list) or not raw_names:
        raise HTTPException(status_code=400, detail="compare-multiple requires a non-empty 'names' list.")

    manager = BaselineManager(paths)
    tests: list[Dict[str, Any]] = []
    skipped: list[str] = []
    for raw_name in raw_names:
        name = str(raw_name).strip()
        if not name:
            continue
        try:
            metadata = manager.load_metadata(name)
        except FileNotFoundError:
            skipped.append(name)
            continue
        capture = metadata.get("capture", {}) or {}
        url = capture.get("url")
        if not url:
            skipped.append(name)
            continue
        test_case: Dict[str, Any] = {"name": name, "url": url}
        if capture.get("browser"):
            test_case["browser"] = capture.get("browser")
        if capture.get("device"):
            test_case["device"] = capture.get("device")
        viewport = capture.get("viewport")
        if isinstance(viewport, (list, tuple)) and len(viewport) == 2:
            test_case["viewport"] = f"{viewport[0]}x{viewport[1]}"
        elif viewport:
            test_case["viewport"] = viewport
        if capture.get("locale"):
            test_case["locale"] = capture.get("locale")
        if capture.get("timezone_id"):
            test_case["timezone_id"] = capture.get("timezone_id")
        if capture.get("color_scheme"):
            test_case["color_scheme"] = capture.get("color_scheme")
        threshold_pct = metadata.get("threshold_pct")
        if threshold_pct is not None:
            test_case["threshold_pct"] = threshold_pct
        tests.append(test_case)

    if not tests:
        raise HTTPException(status_code=404, detail="None of the requested baselines could be found.")

    import tempfile
    import yaml
    tmp_dir = Path(tempfile.gettempdir()) / "vrt-compare-multiple"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    suite_path = tmp_dir / f"suite-{uuid.uuid4().hex}.yaml"
    suite_path.write_text(yaml.safe_dump({"tests": tests}, sort_keys=False), encoding="utf-8")

    # The background subprocess still needs this file after we return, so it
    # is intentionally left on disk in the shared tmp dir (not cleaned up
    # synchronously here) — a leftover suite YAML there is harmless.
    args = ["run-suite", "--suite", str(suite_path), "--create-missing-baseline"]
    task_id = _run_cli_action_async_helper(paths, project_root, port, args)
    return {"ok": True, "task_id": task_id, "count": len(tests), "skipped": skipped}

@app.post("/api/integrations/webhooks")
def post_integrations_webhooks(payload: dict, paths=Depends(get_paths_dep), user=Depends(require_admin)):
    url = str(payload.get("url", "")).strip()
    threshold = float(payload.get("threshold", 1.0))
    manager = IntegrationsManager(paths.root)
    manager.update_webhook(url, threshold)
    _DashboardCache.invalidate(paths)
    return {"ok": True}

@app.post("/api/integrations/rotate-key")
def post_integrations_rotate_key(paths=Depends(get_paths_dep), user=Depends(require_admin)):
    manager = IntegrationsManager(paths.root)
    new_key = manager.rotate_api_key()
    with _API_KEY_LOCK:
        _API_KEY_CACHE.clear()
    return {"ok": True, "api_key": new_key}

@app.post("/api/integrations/reveal-key")
def post_integrations_reveal_key(paths=Depends(get_paths_dep), user=Depends(require_admin)):
    manager = IntegrationsManager(paths.root)
    return {"ok": True, "api_key": manager.reveal_api_key()}

@app.post("/api/integrations/test-webhook")
def post_integrations_test_webhook(payload: dict, paths=Depends(get_paths_dep), user=Depends(require_admin)):
    url = str(payload.get("url", "")).strip()
    if not url:
        raise HTTPException(status_code=400, detail="Webhook URL is required")
    from .notifier import trigger_webhook_detailed
    result = trigger_webhook_detailed(url, {"event": "test_ping", "message": "The Lens Integration Test"})
    manager = IntegrationsManager(paths.root)
    manager.log_activity(
        message="Webhook test succeeded" if result.get("ok") else "Webhook test failed",
        branch="integrations", status="success" if result.get("ok") else "failed",
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail="Webhook test failed")
    return result

@app.post("/api/integrations/github/connect")
def post_integrations_github_connect(paths=Depends(get_paths_dep), port=Depends(get_port_dep), user=Depends(require_admin)):
    manager = IntegrationsManager(paths.root)
    base_url = _get_base_url_helper(port)
    settings = oauth_settings(f"{base_url}/api/integrations/github/callback")
    if not settings["configured"]:
        raise HTTPException(
            status_code=400,
            detail="GitHub OAuth is not configured. Set GITHUB_OAUTH_CLIENT_ID and GITHUB_OAUTH_CLIENT_SECRET on the dashboard server."
        )
    state = manager.begin_github_oauth()
    authorize_url = build_authorize_url(
        client_id=settings["client_id"], redirect_uri=settings["redirect_uri"],
        state=state, scope=settings["scope"],
    )
    return {"ok": True, "authorize_url": authorize_url}

@app.post("/api/integrations/github/disconnect")
def post_integrations_github_disconnect(paths=Depends(get_paths_dep), user=Depends(require_admin)):
    manager = IntegrationsManager(paths.root)
    manager.disconnect_github()
    return {"ok": True}

@app.post("/api/users")
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

@app.post("/api/users/delete")
def post_users_delete(payload: dict, store=Depends(get_store_dep), user=Depends(require_admin)):
    email = str(payload.get("email", "")).strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")
    if user.email == email.lower():
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    all_users = store.list_users()
    target = next((u for u in all_users if u.get("email", "").lower() == email.lower()), None)
    if target and target.get("role") == "admin":
        admin_count = sum(1 for u in all_users if u.get("role") == "admin")
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="Cannot delete the last admin account")
    store.delete_user(email)
    store.audit(user.email, user.role, "users.delete", {"email": email})
    return {"ok": True}

@app.post("/api/users/update")
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
    # deleting them (require_admin gates every user-management endpoint,
    # so there would be no way back in) — guard it the same way delete does.
    would_lose_admin = (role and role != "admin") or disabled is True
    if would_lose_admin:
        all_users = store.list_users()
        target = next((u for u in all_users if u.get("email", "").lower() == email.lower()), None)
        if target and target.get("role") == "admin":
            admin_count = sum(1 for u in all_users if u.get("role") == "admin")
            if admin_count <= 1:
                raise HTTPException(status_code=400, detail="Cannot demote or disable the last admin account")

    try:
        store.update_user(
            email, role=role if role else None,
            disabled=bool(disabled) if disabled is not None else None,
            password=password, display_name=display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    store.audit(user.email, user.role, "users.update", {"email": email})
    return {"ok": True}

@app.post("/api/sdk/snapshot")
def post_sdk_snapshot(payload: dict, request: Request, paths=Depends(get_paths_dep), store=Depends(get_store_dep), authorized=Depends(require_dev_or_admin)):
    auth_hdr = request.headers.get("Authorization") or ""
    client_ip = request.client.host if request.client else "127.0.0.1"
    limiter_key = auth_hdr if auth_hdr else client_ip
    now = time.time()
    window_start = now - 60.0
    with _SDK_LIMITER_LOCK:
        expired_keys = [k for k, ts_list in _SDK_LIMITER.items() if not [t for t in ts_list if t > window_start]]
        for ek in expired_keys:
            _SDK_LIMITER.pop(ek, None)

        timestamps = [t for t in _SDK_LIMITER[limiter_key] if t > window_start]
        if len(timestamps) >= _MAX_SNAPSHOTS_PER_MINUTE:
            raise HTTPException(status_code=429, detail="Rate limit exceeded. Maximum 30 uploads per minute.")
        timestamps.append(now)
        _SDK_LIMITER[limiter_key] = timestamps

    name = str(payload.get("name", "")).strip()
    image_b64 = str(payload.get("image", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="Missing 'name'")
    if ".." in name or "/" in name or "\\" in name:
        raise HTTPException(
            status_code=400, detail="Invalid baseline name: must not contain path separators or '..'"
        )
    if not image_b64:
        raise HTTPException(status_code=400, detail="Missing 'image' (base64 PNG)")

    import base64 as _base64
    try:
        if "," in image_b64:
            image_b64 = image_b64.split(",", 1)[1]
        image_bytes = _base64.b64decode(image_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 image data")

    manager = BaselineManager(paths)

    import cv2 as _cv2
    import numpy as _np
    from .reporter import save_image as _save_image
    decoded_upload = _cv2.imdecode(_np.frombuffer(image_bytes, _np.uint8), _cv2.IMREAD_COLOR)
    if decoded_upload is None:
        raise HTTPException(status_code=400, detail="Uploaded image could not be decoded")

    if not manager.exists(name):
        tmp_dir = paths.root / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f"sdk_baseline_{name}.webp"
        _save_image(tmp_path, decoded_upload)
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
        _DashboardCache.invalidate(paths)
        return {
            "ok": True, "action": "baseline_created", "name": name,
            "message": f"Baseline '{name}' created successfully from SDK upload."
        }

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
    run_dir = paths.runs_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    current_path = run_dir / "current.webp"
    _save_image(current_path, decoded_upload)
    baseline_image_path = manager.resolve_baseline_image_path(name)

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
        baseline_path=baseline_image_path, current_path=current_path,
        pixel_threshold=pixel_threshold, min_region_area=min_region_area,
        ignore_regions=ignore_regions,
    )

    # Called for the copy it performs; the returned path is not needed here.
    _copy_baseline_into_run(baseline_image_path, run_dir)
    diff_overlay_path = run_dir / "diff_overlay.webp"
    binary_diff_path = run_dir / "binary_diff.webp"
    report_path = run_dir / "report.html"
    json_path = run_dir / "result.json"

    save_image(diff_overlay_path, diff_overlay)
    save_image(binary_diff_path, binary_diff)

    ai_model_path = resolve_ai_model_path(paths, None, no_ai)
    ai_assessment = {}
    ai_error = False
    ai_model_available = bool(ai_model_path and ai_model_path.exists())
    if ai_model_available:
        try:
            ai_assessment = assess_result(
                result=result, model_path=ai_model_path,
                baseline_image_path=baseline_image_path, current_image_path=current_path,
            ).to_dict()
        except Exception:
            ai_error = True
            logger.exception("AI assessment failed; falling back to pixel-only decision")

    passed, comparison_decision = decide_pass_fail(
        comparison_mode=comparison_mode, mismatch_pct=result.mismatch_pct,
        threshold_pct=threshold_pct, ai_assessment=ai_assessment,
        ai_model_available=ai_model_available, ai_error=ai_error,
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
        "case_name": name, "baseline_name": name, "suite_name": payload.get("suite_name"),
        "status": "PASS" if passed else "FAIL", "threshold_pct": threshold_pct,
        "comparison_decision": comparison_decision, "ignore_regions": [list(r) for r in ignore_regions],
        "capture": build_capture_metadata(mock_cfg), "result": result.to_dict(),
        "decision": decision_obj, "ai_assessment": ai_assessment,
        "ai_explanation": ai_explanation, "severity": severity,
    }
    write_json(json_path, output_payload)
    generate_html_report(
        report_path=report_path, test_name=name, baseline_image=Path("baseline.webp"),
        current_image=Path("current.webp"), diff_image=Path("diff_overlay.webp"),
        binary_image=Path("binary_diff.webp"), result=result, threshold_pct=threshold_pct,
        ignore_regions=ignore_regions, capture=build_capture_metadata(mock_cfg),
        review=decision_obj, decision_history=[decision_obj], ai_assessment=ai_assessment,
        ai_explanation=ai_explanation, severity=severity, status=output_payload["status"],
    )
    _DashboardCache.invalidate(paths)
    return {
        "ok": True, "action": "compared", "passed": passed, "run_id": run_name,
        "mismatch_pct": result.mismatch_pct, "diff_pixels": result.diff_pixels,
        "regions": len(result.regions), "ai_label": ai_assessment.get("label"),
        "severity": severity.get("label"), "report_url": f"/runs/{run_name}",
        "export_url": f"/api/runs/{run_name}/export"
    }

# --- Static File Serving & Catch-All Frontend ---

@app.get("/baseline/{baseline_name}/{version_or_file:path}")
def get_baseline_file(baseline_name: str, version_or_file: str, paths=Depends(get_paths_dep), authorized=Depends(require_authorized_client)):
    safe_rel = f"{baseline_name}/{version_or_file}"
    safe_p = Path(_safe_path_helper(paths.baselines_dir, safe_rel))
    if not safe_p.is_file() and safe_p.suffix == ".webp":
        # Fall back to .png artifacts captured before the WebP migration.
        legacy_p = safe_p.with_suffix(".png")
        if legacy_p.is_file():
            safe_p = legacy_p
    if not safe_p.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(safe_p, headers={"Cache-Control": "public, max-age=3600"})

@app.get("/artifacts/{run_id}/{file_path:path}")
def get_artifact_file(run_id: str, file_path: str, paths=Depends(get_paths_dep), authorized=Depends(require_authorized_client)):
    safe_rel = f"{run_id}/{file_path}"
    safe_p = Path(_safe_path_helper(paths.runs_dir, safe_rel))
    if not safe_p.is_file() and safe_p.suffix == ".webp":
        # Fall back to .png artifacts captured before the WebP migration.
        legacy_p = safe_p.with_suffix(".png")
        if legacy_p.is_file():
            safe_p = legacy_p
    if not safe_p.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(safe_p, headers={"Cache-Control": "public, max-age=3600"})

@app.get("/demo/styles.css")
def get_demo_styles(project_root=Depends(get_project_root_dep)):
    # Intentional demo/CI hook, not debug leftovers: setting LENS_DEMO_CSS_INJECT=true
    # swaps the demo portal's brand color so a baseline captured beforehand shows a
    # real visual regression, letting us demonstrate/test the tool (and the CI
    # gatekeeper via `check-ci`) actually catching a color-regression defect.
    # Scoped tightly to this one route/file and one known CSS property so it can
    # never be used to inject arbitrary content into other served paths.
    css_path = project_root / "demo_portal" / "styles.css"
    if css_path.is_file():
        if os.environ.get("LENS_DEMO_CSS_INJECT") == "true":
            content = css_path.read_text(encoding="utf-8")
            content = content.replace("--brand: #0f5f8f;", "--brand: #ef4444;")
            return Response(content, media_type="text/css")
        return FileResponse(css_path)
    raise HTTPException(status_code=404, detail="File not found")

@app.get("/demo/{file_path:path}")
def get_demo_file(file_path: str, project_root=Depends(get_project_root_dep)):
    safe_p = Path(_safe_path_helper(project_root / "demo_portal", file_path))
    if not safe_p.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(safe_p)

@app.get("/assets/{file_path:path}")
def get_assets_file(file_path: str, project_root=Depends(get_project_root_dep)):
    frontend_dir = project_root / "dashboard_frontend" / "dist"
    safe_p = Path(_safe_path_helper(frontend_dir / "assets", file_path))
    if not safe_p.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(safe_p)

@app.get("/{path_name:path}")
def get_frontend_fallback(path_name: str, project_root=Depends(get_project_root_dep)):
    if path_name.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")
    frontend_dir = project_root / "dashboard_frontend" / "dist"
    safe_p = Path(_safe_path_helper(frontend_dir, path_name))
    if safe_p.is_file():
        return FileResponse(safe_p)
    fallback_index = frontend_dir / "index.html"
    if fallback_index.is_file():
        return FileResponse(fallback_index)
    raise HTTPException(status_code=404, detail="Frontend build missing. Run npm run build.")


# --- ASGI to BaseHTTPRequestHandler Wrapper for backward compatibility in Unit Tests ---

class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, project_root: Path, paths: WorkspacePaths, port: int, **kwargs):
        self.project_root = project_root
        self.paths = paths
        self.port = port
        self.store = get_store(paths.db_path)
        super().__init__(*args, directory=str(project_root), **kwargs)

    def handle_one_request(self):
        try:
            self.raw_requestline = self.rfile.readline(65537)
            if len(self.raw_requestline) > 65536:
                self.requestline = ''
                self.request_version = ''
                self.command = ''
                self.send_error(414)
                return
            if not self.raw_requestline:
                self.close_connection = True
                return
            if not self.parse_request():
                return
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.run_asgi())
            finally:
                loop.close()
        except socket.timeout as e:
            self.log_error("Request timed out: %r", e)
            self.close_connection = True
            return

    async def run_asgi(self):
        parsed = urlparse(self.path)
        headers = []
        for k, v in self.headers.items():
            headers.append((k.lower().encode("latin-1"), v.encode("latin-1")))
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.0"},
            "http_version": "1.1",
            "server": (self.headers.get("Host", "127.0.0.1"), self.port),
            "client": self.client_address,
            "scheme": "http",
            "method": self.command,
            "path": parsed.path,
            "raw_path": parsed.path.encode("utf-8"),
            "query_string": parsed.query.encode("utf-8"),
            "headers": headers,
            "state": {
                "paths": self.paths,
                "project_root": self.project_root,
                "store": self.store,
                "port": self.port,
            }
        }
        body_bytes = b""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 10 * 1024 * 1024:
            if parsed.path != "/api/runs/upload" or content_length > 50 * 1024 * 1024:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": f"Request body too large ({content_length} bytes, max 10485760)."}).encode("utf-8"))
                return
        if content_length > 0:
            body_bytes = self.rfile.read(content_length)
        async def receive():
            nonlocal body_bytes
            val = {
                "type": "http.request",
                "body": body_bytes,
                "more_body": False
            }
            body_bytes = b""
            return val
        async def send(message):
            if message["type"] == "http.response.start":
                self.send_response(message["status"])
                for k, v in message.get("headers", []):
                    k_str = k.decode("latin-1")
                    v_str = v.decode("latin-1")
                    if k_str.lower() in ("server", "date"):
                        continue
                    self.send_header(k_str, v_str)
                self.end_headers()
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if body:
                    self.wfile.write(body)
                    self.wfile.flush()
        await app(scope, receive, send)


def _refuse_weak_credentials_on_public_bind(host: str) -> None:
    """Refuse to start with factory-default credentials on a non-loopback bind.

    ensure_bootstrap_users() only prints a stderr warning when the default
    admin/user passwords are in effect, which is easy to miss when the
    dashboard is exposed beyond localhost (e.g. --host 0.0.0.0 for LAN
    access). Escalate to a hard failure in that case unless explicitly
    overridden, since anyone on the network could otherwise log in as admin.
    """
    if host in ("127.0.0.1", "localhost", "::1"):
        return
    if os.environ.get("LENS_ALLOW_INSECURE_DEFAULTS") == "1":
        return
    weak_defaults = {"admin1234", "user1234", "password", "admin", "user"}
    admin_password = os.environ.get("LENS_ADMIN_PASSWORD", "admin1234")
    dev_password = os.environ.get("LENS_DEVELOPER_PASSWORD", "user1234")
    if admin_password in weak_defaults or dev_password in weak_defaults:
        raise SystemExit(
            "Refusing to bind to a non-loopback host with default/weak credentials.\n"
            "Set LENS_ADMIN_PASSWORD and LENS_DEVELOPER_PASSWORD to strong values, "
            "or set LENS_ALLOW_INSECURE_DEFAULTS=1 to bypass this check (not recommended)."
        )


def serve_dashboard(project_root: Path, paths: WorkspacePaths, host: str, port: int) -> None:
    _refuse_weak_credentials_on_public_bind(host)
    store = get_store(paths.db_path)
    store.ensure_bootstrap_users()

    global _GLOBAL_SCHEDULER
    from .scheduler import Scheduler
    _GLOBAL_SCHEDULER = Scheduler(store, paths)
    _GLOBAL_SCHEDULER.start()
    
    app.state.paths = paths
    app.state.project_root = project_root
    app.state.store = store
    app.state.port = port

    import signal
    def handle_shutdown(signum, frame):
        logger.info(f"\n[System] Received shutdown signal ({signal.Signals(signum).name}), cleaning up...")
        if _GLOBAL_SCHEDULER:
            try:
                _GLOBAL_SCHEDULER.stop()
            except Exception:
                pass
        _task_executor.shutdown(wait=True)
        close_shared_browser()
        sys.exit(0)

    try:
        signal.signal(signal.SIGINT, handle_shutdown)
        signal.signal(signal.SIGTERM, handle_shutdown)
    except ValueError:
        pass

    def warmup():
        try:
            from .ai_training import _load_legacy_or_hybrid_model
            model_path = paths.models_dir / "visual_ai.pt"
            if model_path.exists():
                logger.info("[AI Warmup] Pre-loading visual AI model...")
                _load_legacy_or_hybrid_model(model_path)
                logger.info("[AI Warmup] Model pre-loaded successfully!")
        except Exception as e:
            logger.warning(f"[AI Warmup Warning] Failed to pre-load model: {e}")
        try:
            get_shared_browser()
            logger.info("[Playwright Pool] Shared browser pre-warmed successfully!")
        except Exception as e:
            logger.warning(f"[Playwright Pool Warning] Failed to pre-warm browser: {e}")
        try:
            db_runs = store._execute_query("SELECT COUNT(*) as count FROM runs_index;", fetch=True)
            db_count = db_runs[0]["count"] if db_runs else 0
            fs_runs = [d for d in paths.runs_dir.iterdir() if d.is_dir() and (d / "result.json").exists()]
            if db_count < len(fs_runs):
                logger.info("[Warmup] Syncing missing disk runs to DB...")
                try:
                    db_run_ids = {r["run_id"] for r in store._execute_query("SELECT run_id FROM runs_index;", fetch=True)}
                except Exception:
                    db_run_ids = set()
                from .dashboard_data import _sanitize_ai_label, _normalize_run_status
                from ._json_cache import JsonCache
                missing_runs = []
                for run_dir in fs_runs:
                    if run_dir.name not in db_run_ids:
                        try:
                            result_file = run_dir / "result.json"
                            payload = JsonCache.read(result_file)
                            result = payload.get("result", {})
                            ai_assessment = payload.get("ai_assessment", {})
                            decision = payload.get("decision") or payload.get("review", {})
                            capture = payload.get("capture", {})
                            severity = payload.get("severity", {})
                            baseline_name = payload.get("baseline_name") or payload.get("case_name")
                            mismatch_pct = result.get("mismatch_pct")
                            ai_label = _sanitize_ai_label(ai_assessment.get("label"))
                            run_payload = {
                                "run_id": run_dir.name, "case_name": payload.get("case_name"),
                                "baseline_name": baseline_name, "suite_name": payload.get("suite_name"),
                                "status": _normalize_run_status(payload.get("status"), decision.get("status")),
                                "decision_status": decision.get("status") or "pending",
                                "decider": decision.get("reviewer") or decision.get("decider") or "",
                                "decision_comment": decision.get("comment") or "",
                                "decided_at": decision.get("timestamp") or "", "mismatch_pct": mismatch_pct,
                                "diff_regions": len(result.get("regions", [])), "ai_label": ai_label,
                                "ai_score": ai_assessment.get("score"), "severity_label": severity.get("label") or "",
                                "browser": capture.get("browser"), "device": capture.get("device"),
                                "locale": capture.get("locale"), "url": capture.get("url"),
                                "report_href": payload.get("report_href") or f"/artifacts/{run_dir.name}/report.html",
                            }
                            missing_runs.append(run_payload)
                        except Exception as load_err:
                            logger.warning(f"Failed to load run from {run_dir.name}: {load_err}")
                if missing_runs:
                    try:
                        store.bulk_insert_runs(missing_runs)
                    except Exception:
                        for run in missing_runs:
                            try:
                                store.upsert_run_index(run)
                            except Exception:
                                pass
                logger.info("[Warmup] DB runs index sync completed successfully!")
        except Exception as e:
            logger.warning(f"[Warmup Warning] Database runs index reconciliation failed: {e}")

    threading.Thread(target=warmup, daemon=True).start()

    try:
        _git_proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(project_root), capture_output=True, text=True,
        )
        _GITHUB_REPO_URL_CACHE["value"] = _git_proc.stdout.strip() if _git_proc.returncode == 0 else ""
    except Exception:
        _GITHUB_REPO_URL_CACHE["value"] = ""

    try:
        _seed_key = IntegrationsManager(paths.root).get_config().get("api_key", "")
        with _API_KEY_LOCK:
            _API_KEY_CACHE["value"] = _seed_key
            _API_KEY_CACHE["expires_at"] = time.time() + _API_KEY_TTL
    except Exception:
        pass

    _display_host = "127.0.0.1" if host in ("0.0.0.0", "", "::") else host
    _STARTUP_BASE_URL["value"] = f"http://{_display_host}:{port}"

    logger.info(f"Starting FastAPI production server at http://{host}:{port}/")
    try:
        uvicorn.run(app, host=host, port=port, log_config=None)
    except KeyboardInterrupt:
        pass
    finally:
        if _GLOBAL_SCHEDULER:
            _GLOBAL_SCHEDULER.stop()
        close_shared_browser()
