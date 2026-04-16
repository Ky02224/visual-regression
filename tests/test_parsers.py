from pathlib import Path

import pytest

from visual_regression.baseline_manager import BaselineManager
from visual_regression.cli import _baseline_name_from_capture, _run_name_for_capture, parse_headers, parse_viewport
from visual_regression.config import WorkspacePaths
from visual_regression.config import CaptureConfig
from visual_regression.image_compare import parse_ignore_regions
from visual_regression.suite_runner import load_suite


def test_parse_viewport_ok():
    assert parse_viewport("1920x1080") == (1920, 1080)


def test_parse_viewport_invalid():
    with pytest.raises(ValueError):
        parse_viewport("1920-1080")


def test_parse_ignore_regions_ok():
    assert parse_ignore_regions(["0,10,100,200"]) == [(0, 10, 100, 200)]


def test_parse_ignore_regions_invalid():
    with pytest.raises(ValueError):
        parse_ignore_regions(["10,20,0,100"])


def test_parse_headers_ok():
    assert parse_headers(["X-Test: one", "Accept-Language: en-US"]) == {
        "X-Test": "one",
        "Accept-Language": "en-US",
    }


def test_normalize_baseline_name(tmp_path: Path):
    manager = BaselineManager(WorkspacePaths(root=tmp_path / ".tmp-test-vr"))
    assert manager.normalize_name("My Home/Page") == "My_Home_Page"


def test_load_suite_ok(tmp_path: Path):
    suite_file = tmp_path / "suite.yaml"
    suite_file.write_text(
        """
tests:
  - name: home
    url: https://example.com
    viewport: [1280, 720]
    threshold_pct: 0.4
    locale: en-US
    timezone_id: Asia/Kuala_Lumpur
    extra_headers:
      X-Test: one
""".strip(),
        encoding="utf-8",
    )
    cases = load_suite(suite_file)
    assert len(cases) == 1
    assert cases[0].name == "home"
    assert cases[0].viewport == (1280, 720)
    assert cases[0].threshold_pct == 0.4
    assert cases[0].locale == "en-US"
    assert cases[0].timezone_id == "Asia/Kuala_Lumpur"
    assert cases[0].extra_headers == {"X-Test": "one"}


def test_baseline_name_from_capture_includes_environment_dimensions():
    name = _baseline_name_from_capture(
        "https://example.com/pricing",
        browser="firefox",
        device="iPhone 13",
        locale="zh-CN",
    )
    assert name == "example.com_pricing_firefox_iPhone_13_zh-CN"


def test_run_name_for_capture_includes_matrix_dimensions():
    cfg = CaptureConfig(
        name="demo-home-en",
        url="https://example.com",
        browser="webkit",
        device="Pixel 7",
        viewport=(1280, 720),
        locale="ms-MY",
    )
    run_name = _run_name_for_capture("demo-home-en", cfg)
    assert "demo-home-en" in run_name
    assert "webkit" in run_name
    assert "Pixel_7" in run_name
    assert "ms-MY" in run_name
