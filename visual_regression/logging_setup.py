"""Logging configuration, with an opt-in JSON formatter.

The server previously called ``logging.basicConfig`` at import time with a plain
text format. That is fine to read over someone's shoulder and useless everywhere
else: a log aggregator cannot filter on fields it has to regex out of a string,
and a single request's lines cannot be tied together at all.

Set ``LENS_LOG_FORMAT=json`` for one JSON object per line. The default stays
text so local runs and the existing docs are unaffected.

A request id is carried in a ContextVar, so every line emitted while handling a
request carries it without each call site having to thread it through.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import time
import uuid
from typing import Any, Dict, Optional

# Set per request by RequestIdMiddleware; read by both formatters.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")

# Attributes LogRecord always carries. Anything outside this set was attached by
# a caller via `extra=` and belongs in the structured output.
_STANDARD_RECORD_FIELDS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with any `extra=` fields merged in."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_FIELDS or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)

        return json.dumps(payload, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """The original human-readable format, plus the request id when there is one."""

    def __init__(self):
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        rid = request_id_var.get()
        return f"{base} [req={rid}]" if rid else base


def configure_logging(level: Optional[str] = None, fmt: Optional[str] = None) -> None:
    """Install the root handler. Safe to call more than once.

    Existing handlers are replaced rather than added to, so repeated calls (a
    test importing the server, then a CLI command configuring it again) cannot
    produce duplicated lines.
    """
    level_name = (level or os.environ.get("LENS_LOG_LEVEL") or "INFO").upper()
    fmt_name = (fmt or os.environ.get("LENS_LOG_FORMAT") or "text").lower()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt_name == "json" else TextFormatter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(getattr(logging, level_name, logging.INFO))


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]
