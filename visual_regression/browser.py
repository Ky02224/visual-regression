from __future__ import annotations

from collections import deque
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from typing import Any
from playwright.sync_api import Playwright, sync_playwright

from .config import CaptureConfig


_DISABLE_ANIMATION_CSS = """
*,
*::before,
*::after {
  transition: none !important;
  animation: none !important;
  caret-color: transparent !important;
}
"""

_PREPARE_PAGE_JS = """
// Freeze HTML5 videos
document.querySelectorAll('video').forEach(video => {
  try {
    video.pause();
    video.currentTime = 0;
  } catch (e) {}
});

// Hide visual masks / ignored dynamic elements
document.querySelectorAll('.visual-mask, [data-visual-mask], .percy-ignore, [data-percy-ignore]').forEach(el => {
  try {
    el.style.visibility = 'hidden';
  } catch (e) {}
});

// Auto-hide cookie consent banners, privacy policies, and terms dialogs
const cookieSelectors = [
  'div[class*="cookie" i]', 'div[id*="cookie" i]',
  'div[class*="consent" i]', 'div[id*="consent" i]',
  'div[class*="privacy" i]', 'div[id*="privacy" i]',
  '[class*="cookie-banner" i]', '[id*="cookie-banner" i]',
  '.cookie-consent', '#cookie-consent', '.privacy-banner',
  'div[class*="gdpr" i]', 'div[id*="gdpr" i]',
  'dialog[class*="cookie" i]', 'dialog[id*="cookie" i]'
];
cookieSelectors.forEach(sel => {
  try {
    document.querySelectorAll(sel).forEach(el => {
      el.style.setProperty('display', 'none', 'important');
    });
  } catch (e) {}
});
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


def capture_website(
    cfg: CaptureConfig,
    output_path: Path,
    playwright_instance: Playwright | None = None,
    browser_instance: Any = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if playwright_instance and browser_instance:
        context = browser_instance.new_context(**_build_context_options(playwright_instance, cfg))
        page = context.new_page()
        try:
            page.goto(cfg.url, wait_until=cfg.wait_until or "networkidle", timeout=cfg.navigation_timeout_ms)
        except Exception as e:
            if "timeout" in str(e).lower():
                print(f"[Warning] Navigation timeout on {cfg.url}. Proceeding to capture screenshot anyway.")
            else:
                raise e
        if cfg.disable_animations:
            page.add_style_tag(content=_DISABLE_ANIMATION_CSS)
        if cfg.hide_selectors:
            selector_rules = "\n".join([f"{selector} {{ visibility: hidden !important; }}" for selector in cfg.hide_selectors])
            page.add_style_tag(content=selector_rules)
        if cfg.wait_for_selector:
            page.wait_for_selector(cfg.wait_for_selector, timeout=cfg.navigation_timeout_ms)
        if cfg.wait_ms > 0:
            page.wait_for_timeout(cfg.wait_ms)

        # Trigger lazy loaded assets
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            page.wait_for_timeout(300)
            page.evaluate("window.scrollTo(0, 0);")
            page.wait_for_timeout(200)
        except Exception:
            pass

        page.evaluate(_PREPARE_PAGE_JS)
        page.screenshot(path=str(output_path), full_page=cfg.full_page)
        context.close()
        return

    with sync_playwright() as playwright:
        if cfg.browser not in {"chromium", "firefox", "webkit"}:
            raise ValueError("browser must be one of: chromium, firefox, webkit")

        browser_type = getattr(playwright, cfg.browser)
        browser = browser_type.launch(headless=True)
        context = browser.new_context(**_build_context_options(playwright, cfg))

        page = context.new_page()
        try:
            page.goto(cfg.url, wait_until=cfg.wait_until or "networkidle", timeout=cfg.navigation_timeout_ms)
        except Exception as e:
            if "timeout" in str(e).lower():
                print(f"[Warning] Navigation timeout on {cfg.url}. Proceeding to capture screenshot anyway.")
            else:
                raise e
        if cfg.disable_animations:
            page.add_style_tag(content=_DISABLE_ANIMATION_CSS)
        if cfg.hide_selectors:
            selector_rules = "\n".join([f"{selector} {{ visibility: hidden !important; }}" for selector in cfg.hide_selectors])
            page.add_style_tag(content=selector_rules)
        if cfg.wait_for_selector:
            page.wait_for_selector(cfg.wait_for_selector, timeout=cfg.navigation_timeout_ms)
        if cfg.wait_ms > 0:
            page.wait_for_timeout(cfg.wait_ms)

        # Trigger lazy loaded assets
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            page.wait_for_timeout(300)
            page.evaluate("window.scrollTo(0, 0);")
            page.wait_for_timeout(200)
        except Exception:
            pass

        page.evaluate(_PREPARE_PAGE_JS)
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
