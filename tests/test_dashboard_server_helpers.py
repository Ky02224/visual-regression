"""Tests for dashboard_server's pure helpers.

The endpoint bodies are covered by test_dashboard_server.py, which boots a real
server. These cover the helpers underneath, which are where the security-relevant
decisions actually live:

* `_safe_path_helper` is the containment check for artifact serving. Get it wrong
  and `/artifacts/../../etc/passwd` reads outside the workspace.
* `_payload_to_args_helper` turns a JSON body into argv for a CLI subprocess.
  Only allow-listed keys may become flags — anything else is a way to smuggle
  arguments into a command the server runs.
* `MetricsCollector` backs /metrics, which is what a monitoring system alerts on.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from visual_regression.dashboard_server import (
    MetricsCollector,
    _get_base_url_helper,
    _payload_to_args_helper,
    _safe_path_helper,
)


# ---------------------------------------------------------------------------
# Path containment
# ---------------------------------------------------------------------------

class TestSafePathHelper:
    def test_resolves_a_path_inside_the_base(self, tmp_path):
        (tmp_path / "runs").mkdir()
        result = _safe_path_helper(tmp_path, "runs/report.html")
        assert str(tmp_path.resolve()) in result
        assert result.endswith("report.html")

    def test_a_traversal_falls_back_to_the_base(self, tmp_path):
        """`..` must not escape the workspace — otherwise the artifact route
        serves arbitrary files off the host."""
        result = _safe_path_helper(tmp_path, "../../../etc/passwd")
        assert result == str(tmp_path.resolve())

    def test_a_traversal_hidden_mid_path_is_also_caught(self, tmp_path):
        result = _safe_path_helper(tmp_path, "runs/../../outside.txt")
        assert result == str(tmp_path.resolve())

    def test_an_absolute_path_does_not_escape(self, tmp_path):
        """Path joining with an absolute right-hand side discards the base
        entirely in pathlib, so this needs its own check."""
        result = _safe_path_helper(tmp_path, "/etc/passwd")
        assert result == str(tmp_path.resolve())

    def test_the_base_itself_is_allowed(self, tmp_path):
        assert _safe_path_helper(tmp_path, ".") == str(tmp_path.resolve())

    def test_a_deeply_nested_path_is_allowed(self, tmp_path):
        result = _safe_path_helper(tmp_path, "a/b/c/d/report.html")
        assert result.endswith("report.html")
        assert str(tmp_path.resolve()) in result


# ---------------------------------------------------------------------------
# Payload to argv
# ---------------------------------------------------------------------------

_ALLOWED = {
    "url": "--url",
    "name": "--name",
    "browser": "--browser",
    "device": "--device",
    "no_ai": "--no-ai",
    "browsers": "--browser",
}


class TestPayloadToArgs:
    def test_maps_an_allowed_key_to_its_flag(self):
        assert _payload_to_args_helper({"url": "http://x"}, _ALLOWED) == ["--url", "http://x"]

    def test_ignores_keys_that_are_not_allow_listed(self):
        """The allow-list is the boundary: an arbitrary key must not become an
        argument to the command the server shells out to."""
        args = _payload_to_args_helper({"url": "http://x", "evil": "--exec"}, _ALLOWED)
        assert "--exec" not in args
        assert "evil" not in args

    def test_skips_none_and_empty_values(self):
        assert _payload_to_args_helper({"url": None, "name": ""}, _ALLOWED) == []

    def test_a_true_boolean_becomes_a_bare_flag(self):
        assert _payload_to_args_helper({"no_ai": True}, _ALLOWED) == ["--no-ai"]

    def test_a_false_boolean_emits_nothing(self):
        assert _payload_to_args_helper({"no_ai": False}, _ALLOWED) == []

    def test_a_list_repeats_the_flag(self):
        args = _payload_to_args_helper({"browsers": ["chromium", "firefox"]}, _ALLOWED)
        assert args == ["--browser", "chromium", "--browser", "firefox"]

    def test_friendly_browser_names_are_translated(self):
        """Users type Chrome and Safari; Playwright wants chromium and webkit."""
        assert _payload_to_args_helper({"browser": "Chrome"}, _ALLOWED) == ["--browser", "chromium"]
        assert _payload_to_args_helper({"browser": "Safari"}, _ALLOWED) == ["--browser", "webkit"]

    def test_browser_names_are_lowercased(self):
        assert _payload_to_args_helper({"browser": "FIREFOX"}, _ALLOWED) == ["--browser", "firefox"]

    def test_desktop_device_is_dropped_rather_than_passed(self):
        """`desktop` is the absence of a device emulation, not a device name."""
        assert _payload_to_args_helper({"device": "desktop"}, _ALLOWED) == []

    def test_a_real_device_is_passed_through(self):
        assert _payload_to_args_helper({"device": "iPhone 13"}, _ALLOWED) == ["--device", "iPhone 13"]

    def test_values_are_stringified(self):
        assert _payload_to_args_helper({"name": 42}, _ALLOWED) == ["--name", "42"]

    def test_an_empty_payload_gives_no_args(self):
        assert _payload_to_args_helper({}, _ALLOWED) == []

    def test_a_value_containing_shell_metacharacters_stays_one_argument(self):
        """argv is a list, never a shell string — the metacharacters must ride
        along as data inside a single element."""
        args = _payload_to_args_helper({"name": "a; rm -rf /"}, _ALLOWED)
        assert args == ["--name", "a; rm -rf /"]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class TestMetricsCollector:
    def test_starts_at_zero(self):
        metrics = MetricsCollector()
        assert metrics.captures_total == 0
        assert metrics.comparisons_total == 0
        assert metrics.ai_inferences_total == 0

    def test_counts_captures_and_failures_separately(self):
        metrics = MetricsCollector()
        metrics.record_capture(1.0, True)
        metrics.record_capture(2.0, False)
        assert metrics.captures_total == 2
        assert metrics.captures_failed == 1

    def test_counts_comparisons_and_failures_separately(self):
        metrics = MetricsCollector()
        metrics.record_compare(0.5, True)
        metrics.record_compare(0.5, False)
        assert metrics.comparisons_total == 2
        assert metrics.comparisons_failed == 1

    def test_records_ai_inferences(self):
        metrics = MetricsCollector()
        metrics.record_ai_inference(0.25)
        assert metrics.ai_inferences_total == 1

    def test_duration_history_is_bounded(self):
        """An unbounded list here would grow for the process's whole lifetime."""
        metrics = MetricsCollector()
        for _ in range(1500):
            metrics.record_capture(1.0, True)
        assert len(metrics.capture_durations) == 1000
        assert metrics.captures_total == 1500

    def test_counters_survive_concurrent_updates(self):
        """Captures are recorded from the worker threads that run them."""
        metrics = MetricsCollector()

        def worker():
            for _ in range(200):
                metrics.record_capture(1.0, True)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert metrics.captures_total == 1000

    def test_prometheus_output_is_line_oriented_with_help_and_type(self):
        class _Store:
            def list_baselines(self):
                return [1, 2, 3]

        text = MetricsCollector().generate_prometheus_text(_Store())
        assert "# HELP vrt_baselines_total" in text
        assert "# TYPE vrt_baselines_total gauge" in text
        assert "vrt_baselines_total 3" in text

    def test_prometheus_output_survives_a_broken_store(self):
        """/metrics is what the monitoring system scrapes; it must not 500 just
        because the database is briefly unavailable."""
        class _BrokenStore:
            def list_baselines(self):
                raise RuntimeError("db down")

        text = MetricsCollector().generate_prometheus_text(_BrokenStore())
        assert "vrt_baselines_total 0" in text


# ---------------------------------------------------------------------------
# Base URL
# ---------------------------------------------------------------------------

class TestBaseUrl:
    def test_falls_back_to_loopback_with_the_given_port(self, monkeypatch):
        monkeypatch.setattr(
            "visual_regression.dashboard_server._STARTUP_BASE_URL", {"value": None}
        )
        assert _get_base_url_helper(8130) == "http://127.0.0.1:8130"

    def test_prefers_the_url_recorded_at_startup(self, monkeypatch):
        """Behind a reverse proxy the loopback URL is wrong in every link the
        dashboard emits, including the ones sent to Slack and GitHub."""
        monkeypatch.setattr(
            "visual_regression.dashboard_server._STARTUP_BASE_URL",
            {"value": "https://lens.example.com"},
        )
        assert _get_base_url_helper(8130) == "https://lens.example.com"
