"""Request-scoped logging context.

Attaches an id to every request so the lines emitted while handling it can be
tied together afterwards. Without this, a failure in a background capture thread
and the request that triggered it are two unrelated log lines.

An inbound X-Request-ID is honoured so a trace started by a proxy or a CI job
survives into these logs; otherwise one is generated. It is echoed back on the
response, which is what lets someone paste an id from a browser's network tab
straight into a log search.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from ..logging_setup import new_request_id, request_id_var

_HEADER = "X-Request-ID"


class RequestIdMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, slow_request_seconds: float = 5.0):
        super().__init__(app)
        self._slow_request_seconds = slow_request_seconds

    async def dispatch(self, request, call_next):
        incoming = request.headers.get(_HEADER, "").strip()
        # Bound the length: this value ends up in every log line for the
        # request, and it arrives from the client.
        request_id = incoming[:64] if incoming else new_request_id()
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)

        elapsed = time.perf_counter() - started
        response.headers[_HEADER] = request_id
        # Surfacing the duration on the response makes a slow endpoint visible
        # from the browser without needing server access.
        response.headers["X-Response-Time-Ms"] = f"{elapsed * 1000:.1f}"
        return response
