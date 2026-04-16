from __future__ import annotations

from collections import deque
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from playwright.sync_api import Playwright, sync_playwright

from .config import CaptureConfig


_DISABLE_ANIMATION_CSS = """
*,
*::before,
*::after {
  animation-delay: 0s !important;
  animation-duration: 0s !important;
  animation-iteration-count: 1 !important;
  transition-delay: 0s !important;
  transition-duration: 0s !important;
  caret-color: transparent !important;
}
"""


def _build_context_options(playwright: Playwright, cfg: CaptureConfig) -> dict:
    options: dict = {}
    if cfg.device:
        if cfg.device not in playwright.devices:
            known = ", ".join(sorted(playwright.devices.keys())[:10])
            raise ValueError(f"Unknown device '{cfg.device}'. Example devices: {known}")
        options.update(playwright.devices[cfg.device])
    else:
        options["viewport"] = {"width": cfg.viewport[0], "height": cfg.viewport[1]}
    if cfg.locale:
        options["locale"] = cfg.locale
    if cfg.timezone_id:
        options["timezone_id"] = cfg.timezone_id
    if cfg.color_scheme:
        options["color_scheme"] = cfg.color_scheme
    if cfg.extra_headers:
        options["extra_http_headers"] = cfg.extra_headers
    return options


def capture_website(cfg: CaptureConfig, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        if cfg.browser not in {"chromium", "firefox", "webkit"}:
            raise ValueError("browser must be one of: chromium, firefox, webkit")

        browser_type = getattr(playwright, cfg.browser)
        browser = browser_type.launch(headless=True)
        context = browser.new_context(**_build_context_options(playwright, cfg))

        page = context.new_page()
        page.goto(cfg.url, wait_until=cfg.wait_until, timeout=cfg.navigation_timeout_ms)
        if cfg.disable_animations:
            page.add_style_tag(content=_DISABLE_ANIMATION_CSS)
        if cfg.hide_selectors:
            selector_rules = "\n".join([f"{selector} {{ visibility: hidden !important; }}" for selector in cfg.hide_selectors])
            page.add_style_tag(content=selector_rules)
        if cfg.wait_for_selector:
            page.wait_for_selector(cfg.wait_for_selector, timeout=cfg.navigation_timeout_ms)
        if cfg.wait_ms > 0:
            page.wait_for_timeout(cfg.wait_ms)

        page.screenshot(path=str(output_path), full_page=cfg.full_page)

        context.close()
        browser.close()


def _normalized_same_domain_href(base_url: str, href: str, domain: str, preserve_query: bool = False) -> str | None:
    if not href:
        return None
    raw = href.strip()
    if not raw or raw.startswith(("#", "javascript:", "mailto:", "tel:")):
        return None
    joined = urljoin(base_url, raw)
    parsed = urlparse(joined)
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc != domain:
        return None
    query = parsed.query if preserve_query else ""
    if preserve_query and query:
        stable_query = urlencode(sorted(parse_qsl(query, keep_blank_values=True)))
        query = stable_query
    normalized = parsed._replace(fragment="", query=query)
    return urlunparse(normalized)


def discover_same_domain_urls(cfg: CaptureConfig, page_limit: int = 30, preserve_query: bool = False) -> list[str]:
    page_limit = max(1, int(page_limit))
    discovered: list[str] = []
    seen: set[str] = set()
    start = urlparse(cfg.url)
    if start.scheme not in {"http", "https"} or not start.netloc:
        raise ValueError("Start URL must be a valid http/https URL")
    start_query = start.query if preserve_query else ""
    if preserve_query and start_query:
        start_query = urlencode(sorted(parse_qsl(start_query, keep_blank_values=True)))
    start_url = urlunparse(start._replace(fragment="", query=start_query))
    queue = deque([start_url])

    with sync_playwright() as playwright:
        if cfg.browser not in {"chromium", "firefox", "webkit"}:
            raise ValueError("browser must be one of: chromium, firefox, webkit")

        browser_type = getattr(playwright, cfg.browser)
        browser = browser_type.launch(headless=True)
        context = browser.new_context(**_build_context_options(playwright, cfg))
        page = context.new_page()

        while queue and len(discovered) < page_limit:
            current_url = queue.popleft()
            if current_url in seen:
                continue
            seen.add(current_url)
            try:
                page.goto(current_url, wait_until=cfg.wait_until, timeout=cfg.navigation_timeout_ms)
                if cfg.disable_animations:
                    page.add_style_tag(content=_DISABLE_ANIMATION_CSS)
                if cfg.wait_ms > 0:
                    page.wait_for_timeout(cfg.wait_ms)
                discovered.append(current_url)
                hrefs = page.eval_on_selector_all(
                    "a[href]",
                    "nodes => nodes.map(node => node.getAttribute('href')).filter(Boolean)",
                )
                for href in hrefs:
                    normalized = _normalized_same_domain_href(current_url, href, start.netloc, preserve_query=preserve_query)
                    if normalized and normalized not in seen and normalized not in queue:
                        queue.append(normalized)
                        if len(queue) + len(discovered) >= page_limit * 3:
                            break
            except Exception:
                continue

        context.close()
        browser.close()

    return discovered
