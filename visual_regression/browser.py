from __future__ import annotations

from collections import deque
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from typing import Any, List, Dict
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

_FIND_DYNAMIC_REGIONS_JS = """
(() => {
  const dynamicBoxes = [];
  document.querySelectorAll('*').forEach(el => {
    if (el.children.length > 0) return;
    const text = (el.textContent || '').trim();
    if (!text) return;
    
    // Regex for dates (e.g. 2026-06-10), times (e.g. 21:55:42), and prices/currencies (e.g. $12.34, ￥99.00)
    const isDate = /\\d{4}[-/.]\\d{2}[-/.]\\d{2}/.test(text) || /\\d{2}[-/.]\\d{2}[-/.]\\d{4}/.test(text);
    const isTime = /\\d{1,2}:\\d{2}(:\\d{2})?\\s*(am|pm)?/i.test(text);
    const isPrice = /^[\\$\\u00A3\\u00A5\\u20AC\\u20A1-\\u20CF\\uFE69\\uFF04\\uFFE0\\uFFE1\\uFFE5\\uFFE6]\\s*\\d+/i.test(text) || /\\d+\\s*(USD|EUR|CNY|MYR)/i.test(text);
    
    const classId = (el.className + ' ' + el.id).toLowerCase();
    const isClassDynamic = classId.includes('date') || classId.includes('time') || classId.includes('timestamp') || classId.includes('clock') || classId.includes('counter') || classId.includes('price');
    
    if (isDate || isTime || isPrice || isClassDynamic) {
      const r = el.getBoundingClientRect();
      if (r.width > 3 && r.height > 3) {
        dynamicBoxes.push({
          x: Math.round(r.left + window.scrollX),
          y: Math.round(r.top + window.scrollY),
          width: Math.round(r.width),
          height: Math.round(r.height)
        });
      }
    }
  });
  return dynamicBoxes;
})()
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


_SHARED_PLAYWRIGHT = None
_SHARED_BROWSER = None

def set_shared_browser(playwright: Playwright | None, browser: Any) -> None:
    global _SHARED_PLAYWRIGHT, _SHARED_BROWSER
    _SHARED_PLAYWRIGHT = playwright
    _SHARED_BROWSER = browser

def _setup_routing_mocks(page: Any, mock_routes: dict[str, Any]) -> None:
    import json
    for pattern, response in mock_routes.items():
        def make_handler(data):
            return lambda route: route.fulfill(
                status=200,
                headers={"content-type": "application/json", "access-control-allow-origin": "*"},
                body=json.dumps(data) if isinstance(data, (dict, list)) else str(data)
            )
        page.route(pattern, make_handler(response))

def capture_website(
    cfg: CaptureConfig,
    output_path: Path,
    playwright_instance: Playwright | None = None,
    browser_instance: Any = None,
) -> List[Dict[str, Any]]:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not playwright_instance and _SHARED_PLAYWRIGHT:
        playwright_instance = _SHARED_PLAYWRIGHT
    if not browser_instance and _SHARED_BROWSER:
        browser_instance = _SHARED_BROWSER

    if playwright_instance and browser_instance:
        context = browser_instance.new_context(**_build_context_options(playwright_instance, cfg))
        page = context.new_page()
        if cfg.mock_routes:
            _setup_routing_mocks(page, cfg.mock_routes)
        try:
            page.goto(cfg.url, wait_until=cfg.wait_until or "networkidle", timeout=cfg.navigation_timeout_ms)
        except Exception as e:
            if "timeout" in str(e).lower():
                print(f"[Warning] Navigation timeout on {cfg.url}. Proceeding to capture screenshot anyway.")
            else:
                raise e
        if cfg.disable_animations:
            page.add_style_tag(content=_DISABLE_ANIMATION_CSS)
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

        # Wait for custom fonts to load fully
        try:
            page.evaluate("document.fonts.ready")
        except Exception:
            pass

        page.evaluate(_PREPARE_PAGE_JS)
        dynamic_regions = []
        try:
            dynamic_regions = page.evaluate(_FIND_DYNAMIC_REGIONS_JS) or []
        except Exception:
            pass
        page.screenshot(path=str(output_path), full_page=cfg.full_page)
        context.close()
        return dynamic_regions

    with sync_playwright() as playwright:
        if cfg.browser not in {"chromium", "firefox", "webkit"}:
            raise ValueError("browser must be one of: chromium, firefox, webkit")

        browser_type = getattr(playwright, cfg.browser)
        browser = browser_type.launch(headless=True)
        context = browser.new_context(**_build_context_options(playwright, cfg))

        page = context.new_page()
        if cfg.mock_routes:
            _setup_routing_mocks(page, cfg.mock_routes)
        try:
            page.goto(cfg.url, wait_until=cfg.wait_until or "networkidle", timeout=cfg.navigation_timeout_ms)
        except Exception as e:
            if "timeout" in str(e).lower():
                print(f"[Warning] Navigation timeout on {cfg.url}. Proceeding to capture screenshot anyway.")
            else:
                raise e
        if cfg.disable_animations:
            page.add_style_tag(content=_DISABLE_ANIMATION_CSS)
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

        # Wait for custom fonts to load fully
        try:
            page.evaluate("document.fonts.ready")
        except Exception:
            pass

        page.evaluate(_PREPARE_PAGE_JS)
        dynamic_regions = []
        try:
            dynamic_regions = page.evaluate(_FIND_DYNAMIC_REGIONS_JS) or []
        except Exception:
            pass
        page.screenshot(path=str(output_path), full_page=cfg.full_page)

        context.close()
        browser.close()
        return dynamic_regions


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
                page.goto(current_url, wait_until=cfg.wait_until or "networkidle", timeout=cfg.navigation_timeout_ms)
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
