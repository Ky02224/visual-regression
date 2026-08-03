from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import yaml


@dataclass
class SuiteCase:
    name: str
    url: str
    # Where the baseline is captured from, when that differs from `url`.
    # Without this a defect-injection case is self-comparing: create-suite-baselines
    # captures the baseline from the very URL the run then compares against, so the
    # two images are pixel-identical and the case can never fail no matter how bad
    # the injected defect is. Point `baseline_url` at the clean page and `url` at
    # the defective one to get a case that SHOULD fail — the only kind that proves
    # the tool detects anything.
    baseline_url: str | None = None
    browser: str = "chromium"
    device: str | None = None
    viewport: Tuple[int, int] = (1440, 900)
    wait_ms: int = 1200
    threshold_pct: float = 0.5
    pixel_threshold: int = 20
    min_region_area: int = 120
    ignore_regions: List[Tuple[int, int, int, int]] = field(default_factory=list)
    locale: str | None = None
    timezone_id: str | None = None
    color_scheme: str = "light"
    extra_headers: Dict[str, str] = field(default_factory=dict)
    wait_for_selector: str | None = None
    comparison_mode: str = "ai"
    hide_selectors: List[str] = field(default_factory=list)


def _parse_viewport(value) -> Tuple[int, int]:
    if isinstance(value, str) and "x" in value:
        width, height = value.split("x", 1)
        return int(width), int(height)
    if isinstance(value, Sequence) and len(value) == 2:
        return int(value[0]), int(value[1])
    return (1440, 900)


def _parse_ignore(value) -> List[Tuple[int, int, int, int]]:
    regions = []
    for item in value or []:
        if not isinstance(item, Sequence) or len(item) != 4:
            raise ValueError(f"Invalid ignore region in suite: {item}")
        x, y, w, h = [int(v) for v in item]
        regions.append((x, y, w, h))
    return regions


def _parse_headers(value) -> Dict[str, str]:
    if not value:
        return {}
    if not isinstance(value, dict):
        raise ValueError("extra_headers must be a mapping")
    return {str(key): str(val) for key, val in value.items()}


def _parse_selectors(value) -> List[str]:
    """Deprecated: hide_selectors is no longer supported. Kept for YAML forward-compat."""
    return []


def load_suite(path: Path) -> List[SuiteCase]:
    from .decision import normalize_comparison_mode

    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    tests = payload.get("tests")
    if not isinstance(tests, list) or not tests:
        raise ValueError("Suite file must contain a non-empty 'tests' list")

    defaults = payload.get("defaults") or {}
    if defaults and not isinstance(defaults, dict):
        raise ValueError("Suite 'defaults' must be a mapping")

    default_comparison_mode = normalize_comparison_mode(defaults.get("comparison_mode"), default="hybrid")

    cases: List[SuiteCase] = []
    for raw in tests:
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid test entry: {raw}")
        raw_baseline_url = raw.get("baseline_url", defaults.get("baseline_url"))
        case = SuiteCase(
            name=str(raw["name"]),
            url=str(raw["url"]),
            baseline_url=str(raw_baseline_url) if raw_baseline_url else None,
            browser=str(raw.get("browser", defaults.get("browser", "chromium"))),
            device=raw.get("device", defaults.get("device")),
            viewport=_parse_viewport(raw.get("viewport", defaults.get("viewport", "1440x900"))),
            wait_ms=int(raw.get("wait_ms", defaults.get("wait_ms", 1200))),
            threshold_pct=float(raw.get("threshold_pct", defaults.get("threshold_pct", 0.5))),
            pixel_threshold=int(raw.get("pixel_threshold", defaults.get("pixel_threshold", 20))),
            min_region_area=int(raw.get("min_region_area", defaults.get("min_region_area", 120))),
            ignore_regions=_parse_ignore(raw.get("ignore_regions", defaults.get("ignore_regions", []))),
            locale=raw.get("locale", defaults.get("locale")),
            timezone_id=raw.get("timezone_id", defaults.get("timezone_id")),
            color_scheme=str(raw.get("color_scheme", defaults.get("color_scheme", "light"))),
            extra_headers=_parse_headers(raw.get("extra_headers", defaults.get("extra_headers"))),
            wait_for_selector=raw.get("wait_for_selector", defaults.get("wait_for_selector")),
            comparison_mode=normalize_comparison_mode(
                raw.get("comparison_mode", default_comparison_mode),
                default=default_comparison_mode,
            ),
            hide_selectors=_parse_selectors(raw.get("hide_selectors", defaults.get("hide_selectors", []))),
        )
        cases.append(case)
    return cases
