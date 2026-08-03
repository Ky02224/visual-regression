"""Tests for the JUnit XML writer.

`write_junit_xml` is what makes suite results legible to a CI server, and it had
no tests at all — a malformed attribute or a miscounted failure would have been
invisible locally and would only show up as a CI run that reports the wrong
number of failures.
"""

from __future__ import annotations

from xml.etree import ElementTree

import pytest

from visual_regression.ci_reporter import write_junit_xml


def _cases() -> list[dict[str, object]]:
    return [
        {"name": "home-desktop", "status": "PASS", "duration_seconds": 1.5,
         "mismatch_pct": 0.01, "threshold_pct": 0.5, "report": "runs/a/report.html"},
        {"name": "home-mobile", "status": "FAIL", "duration_seconds": 2.25,
         "mismatch_pct": 12.5, "threshold_pct": 0.5, "report": "runs/b/report.html",
         "message": "Mismatch too high"},
        {"name": "login", "status": "ERROR", "duration_seconds": 0.0,
         "report": "runs/c/report.html", "message": "Navigation timeout"},
        {"name": "dashboard", "status": "SKIP", "duration_seconds": 0.0,
         "message": "No baseline"},
    ]


@pytest.fixture
def written(tmp_path):
    out = tmp_path / "nested" / "junit.xml"
    write_junit_xml(out, suite_name="demo-suite", cases=_cases(), elapsed_seconds=3.75)
    return out, ElementTree.parse(out).getroot()


class TestSuiteLevelAttributes:
    def test_creates_missing_parent_directories(self, written):
        out, _ = written
        assert out.exists()

    def test_counts_each_status_separately(self, written):
        _, root = written
        assert root.tag == "testsuite"
        assert root.get("name") == "demo-suite"
        assert root.get("tests") == "4"
        assert root.get("failures") == "1"
        assert root.get("errors") == "1"
        assert root.get("skipped") == "1"

    def test_records_elapsed_time_and_a_timestamp(self, written):
        _, root = written
        assert root.get("time") == "3.750"
        assert root.get("timestamp")

    def test_emits_one_testcase_per_case(self, written):
        _, root = written
        assert [tc.get("name") for tc in root.findall("testcase")] == [
            "home-desktop", "home-mobile", "login", "dashboard",
        ]


class TestCaseLevelElements:
    @staticmethod
    def _case(root, name):
        return next(tc for tc in root.findall("testcase") if tc.get("name") == name)

    def test_passing_case_has_no_failure_error_or_skipped_child(self, written):
        _, root = written
        case = self._case(root, "home-desktop")
        assert case.find("failure") is None
        assert case.find("error") is None
        assert case.find("skipped") is None

    def test_failing_case_carries_the_mismatch_and_threshold(self, written):
        _, root = written
        failure = self._case(root, "home-mobile").find("failure")
        assert failure is not None
        assert failure.get("message") == "Mismatch too high"
        assert "12.5" in failure.text
        assert "0.5" in failure.text

    def test_errored_case_uses_an_error_element(self, written):
        _, root = written
        error = self._case(root, "login").find("error")
        assert error is not None
        assert error.get("message") == "Navigation timeout"

    def test_skipped_case_uses_a_skipped_element(self, written):
        _, root = written
        skipped = self._case(root, "dashboard").find("skipped")
        assert skipped is not None
        assert skipped.get("message") == "No baseline"

    def test_durations_are_formatted_to_three_decimals(self, written):
        _, root = written
        assert self._case(root, "home-mobile").get("time") == "2.250"

    def test_system_out_repeats_the_key_numbers(self, written):
        _, root = written
        out = self._case(root, "home-mobile").find("system-out")
        assert "status=FAIL" in out.text
        assert "mismatch_pct=12.5" in out.text


class TestDefaults:
    def test_failure_without_a_message_gets_a_default(self, tmp_path):
        out = tmp_path / "junit.xml"
        write_junit_xml(out, "s", [{"name": "x", "status": "FAIL"}], 1.0)
        failure = ElementTree.parse(out).getroot().find("testcase/failure")
        assert failure.get("message") == "Visual mismatch"

    def test_missing_duration_defaults_to_zero(self, tmp_path):
        out = tmp_path / "junit.xml"
        write_junit_xml(out, "s", [{"name": "x", "status": "PASS"}], 1.0)
        assert ElementTree.parse(out).getroot().find("testcase").get("time") == "0.000"

    def test_empty_suite_is_still_valid_xml(self, tmp_path):
        out = tmp_path / "junit.xml"
        write_junit_xml(out, "empty", [], 0.0)
        root = ElementTree.parse(out).getroot()
        assert root.get("tests") == "0"
        assert root.findall("testcase") == []

    def test_output_declares_its_encoding(self, tmp_path):
        """CI parsers reject a file whose declared encoding is missing or wrong."""
        out = tmp_path / "junit.xml"
        write_junit_xml(out, "s", [{"name": "x", "status": "PASS"}], 1.0)
        assert out.read_bytes().startswith(b"<?xml version='1.0' encoding='utf-8'?>")
