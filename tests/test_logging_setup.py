"""Tests for structured logging and request correlation.

The server used to call logging.basicConfig with a plain text format. That is
readable over someone's shoulder and useless to a log aggregator, which cannot
filter on fields it has to regex out of a message string — and there was no way
at all to tie together the lines belonging to one request.

These pin the JSON shape, that `extra=` fields survive into it, and that the
request id set by the middleware reaches every line emitted underneath.
"""

from __future__ import annotations

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from visual_regression.api.middleware import RequestIdMiddleware
from visual_regression.logging_setup import (
    JsonFormatter,
    TextFormatter,
    configure_logging,
    new_request_id,
    request_id_var,
)


def _record(msg="hello", level=logging.INFO, **extra):
    record = logging.LogRecord("test.logger", level, "f.py", 10, msg, (), None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


@pytest.fixture(autouse=True)
def _clear_request_id():
    token = request_id_var.set("")
    yield
    request_id_var.reset(token)


class TestJsonFormatter:
    def test_emits_one_parseable_object(self):
        payload = json.loads(JsonFormatter().format(_record()))
        assert payload["message"] == "hello"
        assert payload["level"] == "INFO"
        assert payload["logger"] == "test.logger"
        assert payload["ts"].endswith("Z")

    def test_includes_the_request_id_when_one_is_set(self):
        request_id_var.set("abc123")
        assert json.loads(JsonFormatter().format(_record()))["request_id"] == "abc123"

    def test_omits_the_request_id_outside_a_request(self):
        """Background jobs and CLI runs have no request; an empty string field
        would be noise in every one of their lines."""
        assert "request_id" not in json.loads(JsonFormatter().format(_record()))

    def test_extra_fields_become_top_level_keys(self):
        """This is the point of structured logging: `run_id` should be a field
        to filter on, not a substring of the message."""
        payload = json.loads(JsonFormatter().format(_record(run_id="run-1", mismatch=2.5)))
        assert payload["run_id"] == "run-1"
        assert payload["mismatch"] == 2.5

    def test_an_unserialisable_extra_falls_back_to_repr(self):
        """A logging call must never be the thing that raises."""
        payload = json.loads(JsonFormatter().format(_record(obj=object())))
        assert "object" in payload["obj"]

    def test_formats_message_arguments(self):
        record = logging.LogRecord("t", logging.INFO, "f.py", 1, "hi %s", ("bob",), None)
        assert json.loads(JsonFormatter().format(record))["message"] == "hi bob"

    def test_includes_an_exception_traceback(self):
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            record = logging.LogRecord("t", logging.ERROR, "f.py", 1, "failed", (), sys.exc_info())
        payload = json.loads(JsonFormatter().format(record))
        assert "ValueError: boom" in payload["exception"]

    def test_non_ascii_survives_unescaped(self):
        payload = json.loads(JsonFormatter().format(_record("基线已更新")))
        assert payload["message"] == "基线已更新"


class TestTextFormatter:
    def test_keeps_the_original_readable_shape(self):
        line = TextFormatter().format(_record())
        assert "INFO" in line and "test.logger" in line and "hello" in line

    def test_appends_the_request_id_when_present(self):
        request_id_var.set("abc123")
        assert "[req=abc123]" in TextFormatter().format(_record())

    def test_adds_nothing_outside_a_request(self):
        assert "[req=" not in TextFormatter().format(_record())


class TestConfigureLogging:
    def test_json_format_is_selectable_by_env(self, monkeypatch):
        monkeypatch.setenv("LENS_LOG_FORMAT", "json")
        configure_logging()
        assert isinstance(logging.getLogger().handlers[0].formatter, JsonFormatter)

    def test_defaults_to_text(self, monkeypatch):
        monkeypatch.delenv("LENS_LOG_FORMAT", raising=False)
        configure_logging()
        assert isinstance(logging.getLogger().handlers[0].formatter, TextFormatter)

    def test_level_is_selectable(self, monkeypatch):
        monkeypatch.setenv("LENS_LOG_LEVEL", "WARNING")
        configure_logging()
        assert logging.getLogger().level == logging.WARNING

    def test_calling_twice_does_not_duplicate_handlers(self, monkeypatch):
        """The server configures at import and a CLI command may configure
        again; duplicated handlers would print every line twice."""
        monkeypatch.delenv("LENS_LOG_FORMAT", raising=False)
        configure_logging()
        configure_logging()
        assert len(logging.getLogger().handlers) == 1

    def test_an_unknown_level_falls_back_to_info(self, monkeypatch):
        monkeypatch.setenv("LENS_LOG_LEVEL", "NOT_A_LEVEL")
        configure_logging()
        assert logging.getLogger().level == logging.INFO


class TestRequestId:
    def test_ids_are_unique(self):
        assert len({new_request_id() for _ in range(200)}) == 200


class TestRequestIdMiddleware:
    @staticmethod
    def _app():
        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)

        @app.get("/echo")
        def echo():
            return {"seen": request_id_var.get()}

        return TestClient(app)

    def test_generates_an_id_and_echoes_it(self):
        response = self._app().get("/echo")
        assert response.headers["X-Request-ID"]
        assert response.json()["seen"] == response.headers["X-Request-ID"]

    def test_honours_an_inbound_id(self):
        """A trace started by a proxy or CI job should survive into these logs."""
        response = self._app().get("/echo", headers={"X-Request-ID": "trace-from-ci"})
        assert response.headers["X-Request-ID"] == "trace-from-ci"
        assert response.json()["seen"] == "trace-from-ci"

    def test_a_long_inbound_id_is_truncated(self):
        """It is client-supplied and lands in every log line for the request."""
        response = self._app().get("/echo", headers={"X-Request-ID": "x" * 500})
        assert len(response.headers["X-Request-ID"]) == 64

    def test_reports_the_response_time(self):
        assert float(self._app().get("/echo").headers["X-Response-Time-Ms"]) >= 0.0

    def test_the_context_does_not_leak_between_requests(self):
        client = self._app()
        first = client.get("/echo").json()["seen"]
        second = client.get("/echo").json()["seen"]
        assert first != second
