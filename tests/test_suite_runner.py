from pathlib import Path

import pytest

from visual_regression.suite_runner import (
    SuiteCase,
    _parse_headers,
    _parse_ignore,
    _parse_selectors,
    _parse_viewport,
    load_suite,
)


def _write_suite(tmp_path: Path, content: str) -> Path:
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(content, encoding="utf-8")
    return suite_path


# ---------------------------------------------------------------------------
# load_suite: minimal valid suite / defaults
# ---------------------------------------------------------------------------


def test_minimal_suite_applies_sensible_defaults(tmp_path: Path):
    suite_path = _write_suite(
        tmp_path,
        """
        tests:
          - name: home
            url: http://example.test/
        """,
    )

    cases = load_suite(suite_path)

    assert len(cases) == 1
    case = cases[0]
    assert isinstance(case, SuiteCase)
    assert case.name == "home"
    assert case.url == "http://example.test/"
    assert case.browser == "chromium"
    assert case.device is None
    assert case.viewport == (1440, 900)
    assert case.wait_ms == 1200
    assert case.threshold_pct == 0.5
    assert case.pixel_threshold == 20
    assert case.min_region_area == 120
    assert case.ignore_regions == []
    assert case.locale is None
    assert case.timezone_id is None
    assert case.color_scheme == "light"
    assert case.extra_headers == {}
    assert case.wait_for_selector is None
    # No defaults.comparison_mode given -> falls back to "hybrid".
    assert case.comparison_mode == "hybrid"
    assert case.hide_selectors == []


def test_defaults_block_applied_when_case_omits_fields(tmp_path: Path):
    suite_path = _write_suite(
        tmp_path,
        """
        defaults:
          browser: firefox
          viewport: "1920x1080"
          wait_ms: 2000
          threshold_pct: 1.5
          pixel_threshold: 40
          min_region_area: 200
          locale: en-US
          timezone_id: Asia/Kuala_Lumpur
          color_scheme: dark
          comparison_mode: pixel

        tests:
          - name: home
            url: http://example.test/
        """,
    )

    cases = load_suite(suite_path)
    case = cases[0]

    assert case.browser == "firefox"
    assert case.viewport == (1920, 1080)
    assert case.wait_ms == 2000
    assert case.threshold_pct == 1.5
    assert case.pixel_threshold == 40
    assert case.min_region_area == 200
    assert case.locale == "en-US"
    assert case.timezone_id == "Asia/Kuala_Lumpur"
    assert case.color_scheme == "dark"
    assert case.comparison_mode == "pixel"


def test_per_case_values_override_defaults(tmp_path: Path):
    suite_path = _write_suite(
        tmp_path,
        """
        defaults:
          browser: firefox
          viewport: "1920x1080"
          wait_ms: 2000
          threshold_pct: 1.5
          comparison_mode: pixel

        tests:
          - name: home
            url: http://example.test/
            browser: webkit
            viewport: [800, 600]
            wait_ms: 500
            threshold_pct: 0.1
            comparison_mode: ai
          - name: about
            url: http://example.test/about
        """,
    )

    cases = load_suite(suite_path)
    assert len(cases) == 2

    overridden, inherited = cases[0], cases[1]

    assert overridden.browser == "webkit"
    assert overridden.viewport == (800, 600)
    assert overridden.wait_ms == 500
    assert overridden.threshold_pct == 0.1
    assert overridden.comparison_mode == "ai"

    # Second case did not override -> inherits from defaults.
    assert inherited.browser == "firefox"
    assert inherited.viewport == (1920, 1080)
    assert inherited.wait_ms == 2000
    assert inherited.threshold_pct == 1.5
    assert inherited.comparison_mode == "pixel"


def test_realistic_multi_case_suite_like_demo(tmp_path: Path):
    # Modeled on the shape of suite.demo.yaml at the repo root.
    suite_path = _write_suite(
        tmp_path,
        """
        defaults:
          comparison_mode: ai

        tests:
          - name: demo-home-en
            url: http://127.0.0.1:8130/demo/index.html?lang=en-US
            browser: chromium
            viewport: [1440, 900]
            wait_ms: 400
            threshold_pct: 0.25
            pixel_threshold: 20
            min_region_area: 120
            locale: en-US
            timezone_id: Asia/Kuala_Lumpur
            ignore_regions: []

          - name: demo-home-mobile
            url: http://127.0.0.1:8130/demo/index.html?lang=en-US
            browser: chromium
            device: iPhone 13
            viewport: [390, 844]
            wait_ms: 400
            threshold_pct: 0.35
            pixel_threshold: 20
            min_region_area: 100
            locale: en-US
            timezone_id: Asia/Kuala_Lumpur
            ignore_regions: []
        """,
    )

    cases = load_suite(suite_path)
    assert len(cases) == 2
    assert cases[0].comparison_mode == "ai"
    assert cases[1].device == "iPhone 13"
    assert cases[1].viewport == (390, 844)


# ---------------------------------------------------------------------------
# _parse_viewport
# ---------------------------------------------------------------------------


def test_parse_viewport_string_form():
    assert _parse_viewport("1920x1080") == (1920, 1080)


def test_parse_viewport_tuple_and_list_form():
    assert _parse_viewport((800, 600)) == (800, 600)
    assert _parse_viewport([800, 600]) == (800, 600)


@pytest.mark.parametrize("value", [None, "not-a-viewport", 123, [1440], {}])
def test_parse_viewport_invalid_falls_back_to_default(value):
    assert _parse_viewport(value) == (1440, 900)


# ---------------------------------------------------------------------------
# _parse_ignore
# ---------------------------------------------------------------------------


def test_parse_ignore_valid_list_of_4_tuples():
    regions = _parse_ignore([[0, 0, 100, 50], (10, 20, 30, 40)])
    assert regions == [(0, 0, 100, 50), (10, 20, 30, 40)]


def test_parse_ignore_empty_or_none_returns_empty_list():
    assert _parse_ignore(None) == []
    assert _parse_ignore([]) == []


def test_parse_ignore_invalid_entry_length_raises_value_error():
    with pytest.raises(ValueError):
        _parse_ignore([[0, 0, 100]])


def test_parse_ignore_via_load_suite_raises_value_error(tmp_path: Path):
    suite_path = _write_suite(
        tmp_path,
        """
        tests:
          - name: home
            url: http://example.test/
            ignore_regions:
              - [0, 0, 100]
        """,
    )
    with pytest.raises(ValueError):
        load_suite(suite_path)


# ---------------------------------------------------------------------------
# _parse_headers
# ---------------------------------------------------------------------------


def test_parse_headers_valid_dict_str_coerces_keys_and_values():
    headers = _parse_headers({"X-Test": 1, 2: "value"})
    assert headers == {"X-Test": "1", "2": "value"}


@pytest.mark.parametrize("value", [None, {}])
def test_parse_headers_empty_or_none_returns_empty_dict(value):
    assert _parse_headers(value) == {}


def test_parse_headers_non_dict_raises_value_error():
    with pytest.raises(ValueError):
        _parse_headers(["not", "a", "dict"])


# ---------------------------------------------------------------------------
# _parse_selectors (deprecated)
# ---------------------------------------------------------------------------


def test_parse_selectors_always_returns_empty_list():
    assert _parse_selectors(["a", "b"]) == []
    assert _parse_selectors(None) == []
    assert _parse_selectors("whatever") == []


# ---------------------------------------------------------------------------
# load_suite: structural validation errors
# ---------------------------------------------------------------------------


def test_missing_tests_key_raises_value_error(tmp_path: Path):
    suite_path = _write_suite(tmp_path, "defaults:\n  browser: chromium\n")
    with pytest.raises(ValueError):
        load_suite(suite_path)


def test_empty_tests_list_raises_value_error(tmp_path: Path):
    suite_path = _write_suite(tmp_path, "tests: []\n")
    with pytest.raises(ValueError):
        load_suite(suite_path)


def test_non_dict_test_entry_raises_value_error(tmp_path: Path):
    suite_path = _write_suite(
        tmp_path,
        """
        tests:
          - "just-a-string"
        """,
    )
    with pytest.raises(ValueError):
        load_suite(suite_path)


def test_defaults_not_a_mapping_raises_value_error(tmp_path: Path):
    suite_path = _write_suite(
        tmp_path,
        """
        defaults: "not-a-mapping"
        tests:
          - name: home
            url: http://example.test/
        """,
    )
    with pytest.raises(ValueError):
        load_suite(suite_path)


# ---------------------------------------------------------------------------
# comparison_mode normalization
# ---------------------------------------------------------------------------


def test_comparison_mode_defaults_to_hybrid_when_unspecified(tmp_path: Path):
    suite_path = _write_suite(
        tmp_path,
        """
        tests:
          - name: home
            url: http://example.test/
        """,
    )
    cases = load_suite(suite_path)
    assert cases[0].comparison_mode == "hybrid"


@pytest.mark.parametrize("mode", ["pixel", "ai", "hybrid"])
def test_comparison_mode_valid_values_from_defaults(tmp_path: Path, mode: str):
    suite_path = _write_suite(
        tmp_path,
        f"""
        defaults:
          comparison_mode: {mode}
        tests:
          - name: home
            url: http://example.test/
        """,
    )
    cases = load_suite(suite_path)
    assert cases[0].comparison_mode == mode


def test_comparison_mode_per_case_overrides_defaults(tmp_path: Path):
    suite_path = _write_suite(
        tmp_path,
        """
        defaults:
          comparison_mode: pixel
        tests:
          - name: home
            url: http://example.test/
            comparison_mode: ai
        """,
    )
    cases = load_suite(suite_path)
    assert cases[0].comparison_mode == "ai"


def test_comparison_mode_invalid_value_raises_value_error(tmp_path: Path):
    suite_path = _write_suite(
        tmp_path,
        """
        tests:
          - name: home
            url: http://example.test/
            comparison_mode: not-a-real-mode
        """,
    )
    with pytest.raises(ValueError):
        load_suite(suite_path)
