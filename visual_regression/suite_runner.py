from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import yaml


@dataclass
class SuiteCase:
    name: str
    url: str
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
    hide_selectors: List[str] = field(default_factory=list)
    wait_for_selector: str | None = None


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
    if not value:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("hide_selectors must be a list")
    return [str(item) for item in value]


def load_suite(path: Path) -> List[SuiteCase]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    tests = payload.get("tests")
    if not isinstance(tests, list) or not tests:
        raise ValueError("Suite file must contain a non-empty 'tests' list")

    cases: List[SuiteCase] = []
    for raw in tests:
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid test entry: {raw}")
        case = SuiteCase(
            name=str(raw["name"]),
            url=str(raw["url"]),
            browser=str(raw.get("browser", "chromium")),
            device=raw.get("device"),
            viewport=_parse_viewport(raw.get("viewport", "1440x900")),
            wait_ms=int(raw.get("wait_ms", 1200)),
            threshold_pct=float(raw.get("threshold_pct", 0.5)),
            pixel_threshold=int(raw.get("pixel_threshold", 20)),
            min_region_area=int(raw.get("min_region_area", 120)),
            ignore_regions=_parse_ignore(raw.get("ignore_regions", [])),
            locale=raw.get("locale"),
            timezone_id=raw.get("timezone_id"),
            color_scheme=str(raw.get("color_scheme", "light")),
            extra_headers=_parse_headers(raw.get("extra_headers")),
            hide_selectors=_parse_selectors(raw.get("hide_selectors")),
            wait_for_selector=raw.get("wait_for_selector"),
        )
        cases.append(case)
    return cases
