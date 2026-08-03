"""Tests for the scheduler router's suite-path guard.

`suite_path` comes from the request body and is stored, then later handed to a
subprocess the scheduler runs on a timer. So it is a caller-supplied path that
turns into an executed command argument — worth its own containment check rather
than trusting `.is_file()` to reject whatever resolves.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from visual_regression.api.scheduler_routes import _safe_relative_suite_path


@pytest.fixture
def project(tmp_path):
    (tmp_path / "suites").mkdir()
    (tmp_path / "suites" / "demo.yaml").write_text("tests: []", encoding="utf-8")
    (tmp_path / "top.yml").write_text("tests: []", encoding="utf-8")
    return tmp_path


class TestSafeRelativeSuitePath:
    def test_accepts_a_nested_suite(self, project):
        assert _safe_relative_suite_path(project, "suites/demo.yaml").replace("\\", "/") == "suites/demo.yaml"

    def test_accepts_a_top_level_suite(self, project):
        assert _safe_relative_suite_path(project, "top.yml") == "top.yml"

    def test_returns_a_path_relative_to_the_project(self, project):
        """The scheduler runs jobs with project_root as the working directory,
        so an absolute path stored here would break on any other machine."""
        result = _safe_relative_suite_path(project, "suites/demo.yaml")
        assert not result.startswith(str(project))

    def test_strips_surrounding_whitespace(self, project):
        assert _safe_relative_suite_path(project, "  suites/demo.yaml  ").endswith("demo.yaml")

    @pytest.mark.parametrize("bad", ["suite.json", "suite.txt", "suite", "suite.yaml.exe"])
    def test_rejects_a_non_yaml_extension(self, project, bad):
        with pytest.raises(HTTPException) as exc:
            _safe_relative_suite_path(project, bad)
        assert exc.value.status_code == 400
        assert "yaml" in exc.value.detail.lower()

    def test_rejects_a_traversal_out_of_the_project(self, project, tmp_path):
        outside = tmp_path.parent / "outside.yaml"
        outside.write_text("tests: []", encoding="utf-8")
        with pytest.raises(HTTPException) as exc:
            _safe_relative_suite_path(project, "../outside.yaml")
        assert exc.value.status_code == 400
        assert "inside the project" in exc.value.detail

    def test_rejects_a_traversal_hidden_mid_path(self, project, tmp_path):
        outside = tmp_path.parent / "outside.yaml"
        outside.write_text("tests: []", encoding="utf-8")
        with pytest.raises(HTTPException) as exc:
            _safe_relative_suite_path(project, "suites/../../outside.yaml")
        assert exc.value.status_code == 400

    def test_rejects_an_absolute_path_outside_the_project(self, project, tmp_path):
        outside = tmp_path.parent / "outside.yaml"
        outside.write_text("tests: []", encoding="utf-8")
        with pytest.raises(HTTPException) as exc:
            _safe_relative_suite_path(project, str(outside))
        assert exc.value.status_code == 400

    def test_rejects_a_path_that_does_not_exist(self, project):
        with pytest.raises(HTTPException) as exc:
            _safe_relative_suite_path(project, "suites/missing.yaml")
        assert exc.value.status_code == 400
        assert "not found" in exc.value.detail
