from __future__ import annotations

import asyncio
import logging
from collections import deque
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from typing import Any, List, Dict
from playwright.sync_api import Playwright, sync_playwright

logger = logging.getLogger(__name__)


from .config import CaptureConfig
import os
import threading
import time

VIEWPORT_PRESETS = {
    "desktop": (1440, 900),
    "tablet": (768, 1024),
    "mobile": (375, 812),
}

def parse_viewports(viewports_str_or_list: str | list[str] | None) -> list[tuple[str, tuple[int, int]]]:
    """Parse user selected viewports. Defaults to [('desktop', (1440, 900))]."""
    if not viewports_str_or_list:
        return [("desktop", VIEWPORT_PRESETS["desktop"])]
    if isinstance(viewports_str_or_list, str):
        tokens = [t.strip().lower() for t in viewports_str_or_list.split(",") if t.strip()]
    else:
        tokens = [str(t).strip().lower() for t in viewports_str_or_list if str(t).strip()]
    
    result = []
    for token in tokens:
        if token in VIEWPORT_PRESETS:
            result.append((token, VIEWPORT_PRESETS[token]))
        elif "x" in token:
            try:
                w, h = token.split("x", 1)
                result.append((token, (int(w), int(h))))
            except Exception:
                pass
    return result or [("desktop", VIEWPORT_PRESETS["desktop"])]


def validate_url_ssrf(url: str, allow_local: bool = True) -> str:
    """Validate URL scheme and restrict cloud metadata SSRF vectors."""
    if not url:
        return url
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Invalid URL scheme '{parsed.scheme}'. Only http and https are allowed.")
    hostname = (parsed.hostname or "").lower()
    if not allow_local or os.environ.get("VRT_STRICT_SSRF") == "true":
        if hostname in {"169.254.169.254", "metadata.google.internal"} or hostname.startswith("169.254."):
            raise ValueError(f"Access to restricted metadata IP '{hostname}' is blocked for security.")
    return url

# Cache of logged-in storage state per (login_url, credentials, selectors) so a
# batch capture run across many pages doesn't re-run the login flow for each one.
_LOGIN_SESSION_LOCK = threading.Lock()
_LOGIN_SESSION_CACHE: dict = {}
_SESSION_TTL = 600.0


def _perform_login_and_get_state(playwright_instance: Playwright, browser_instance: Any, cfg: CaptureConfig) -> dict | None:
    login_url = getattr(cfg, "login_url", None)
    username_selector = getattr(cfg, "username_selector", None)
    password_selector = getattr(cfg, "password_selector", None)
    submit_selector = getattr(cfg, "submit_selector", None)
    login_username = getattr(cfg, "login_username", None)
    login_password = getattr(cfg, "login_password", None)
    
    if not login_url or not login_username or not login_password:
        return None
        
    cache_key = (
        login_url,
        login_username,
        login_password,
        username_selector,
        password_selector,
        submit_selector
    )
    
    now = time.time()
    with _LOGIN_SESSION_LOCK:
        expired_keys = [k for k, (_, t) in _LOGIN_SESSION_CACHE.items() if now - t >= _SESSION_TTL]
        for k in expired_keys:
            _LOGIN_SESSION_CACHE.pop(k, None)

        if cache_key in _LOGIN_SESSION_CACHE:
            state, saved_time = _LOGIN_SESSION_CACHE[cache_key]
            if now - saved_time < _SESSION_TTL:
                print(f"[AUTO-LOGIN] Cache hit for {login_url}. Reusing active login session state.", flush=True)
                return state

    context = None
    try:
        # Create a clean context for login using the shared browser instance
        context = browser_instance.new_context(**_build_context_options(playwright_instance, cfg))
        page = context.new_page()
        page.goto(login_url, wait_until="networkidle", timeout=cfg.navigation_timeout_ms)

        # Clean / strip selectors
        username_selector = (username_selector or "").strip()
        password_selector = (password_selector or "").strip()
        submit_selector = (submit_selector or "").strip()

        # Scope auto-detected fallback selectors to the <form> that contains the
        # password field, so we don't fill/click an unrelated form on the login
        # page (e.g. a newsletter signup or search box) when nothing explicit is configured.
        search_root = page
        try:
            form_scope = page.locator('form:has(input[type="password"])').first
            if form_scope.count() > 0:
                search_root = form_scope
        except Exception:
            pass

        # Auto-detect username selector if empty
        if not username_selector:
            for sel in [
                'input[type="email"]',
                'input[name*="username" i]',
                'input[name*="email" i]',
                'input[name*="login" i]',
                'input[id*="username" i]',
                'input[id*="email" i]',
                'input[id*="login" i]',
                'input[type="text"]'
            ]:
                try:
                    if search_root.locator(sel).first.is_visible(timeout=500):
                        username_selector = sel
                        print(f"[AUTO-LOGIN] Auto-detected username selector: {sel}")
                        break
                except Exception:
                    pass
            if not username_selector:
                username_selector = 'input[type="text"]'

        # Auto-detect password selector if empty
        if not password_selector:
            for sel in [
                'input[type="password"]',
                'input[name*="password" i]',
                'input[id*="password" i]'
            ]:
                try:
                    if search_root.locator(sel).first.is_visible(timeout=500):
                        password_selector = sel
                        print(f"[AUTO-LOGIN] Auto-detected password selector: {sel}")
                        break
                except Exception:
                    pass
            if not password_selector:
                password_selector = 'input[type="password"]'

        # Auto-detect submit selector if empty
        if not submit_selector:
            for sel in [
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Login")',
                'button:has-text("Sign in")',
                'button:has-text("登录")',
                'button:has-text("Submit")',
                'button',
                'input[type="button"]'
            ]:
                try:
                    if search_root.locator(sel).first.is_visible(timeout=500):
                        submit_selector = sel
                        print(f"[AUTO-LOGIN] Auto-detected submit selector: {sel}")
                        break
                except Exception:
                    pass
            if not submit_selector:
                submit_selector = 'button'

        # Fill login form (still scoped to search_root so a selector that matches
        # multiple elements page-wide but only one within the login form resolves correctly)
        search_root.locator(username_selector).first.fill(login_username or "")
        search_root.locator(password_selector).first.fill(login_password or "")

        # Submit form
        try:
            with page.expect_navigation(wait_until="networkidle", timeout=15000):
                search_root.locator(submit_selector).first.click()
        except Exception:
            search_root.locator(submit_selector).first.click()
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                page.wait_for_timeout(1000)
            
        # Get storage state in memory
        state = context.storage_state()
        with _LOGIN_SESSION_LOCK:
            _LOGIN_SESSION_CACHE[cache_key] = (state, now)
        print(f"[LOGIN SUCCESS] Authenticated successfully at {login_url}")
        return state
    except Exception as e:
        print(f"[LOGIN ERROR] Failed to authenticate at {login_url}: {e}")
        return None
    finally:
        if context:
            try:
                context.close()
            except Exception:
                pass



# WebP encodes width/height as 14-bit fields, so it hard-caps both dimensions
# at 16383px. Full-page screenshots of long pages can exceed that.
_WEBP_MAX_DIMENSION = 16383


def _encode_and_write_screenshot(img_bytes: bytes, output_path: Path, source_url: str) -> None:
    """Decode a raw screenshot and write it to output_path as WebP, falling
    back to PNG bytes under the same path if the image is too large for WebP
    (or WebP encoding otherwise fails) rather than losing the capture."""
    import cv2 as _cv2
    import numpy as _np
    img = _cv2.imdecode(_np.frombuffer(img_bytes, _np.uint8), _cv2.IMREAD_COLOR)
    if img is None or img.size == 0 or img.shape[0] == 0 or img.shape[1] == 0:
        raise ValueError(f"Captured screenshot for {source_url!r} could not be decoded into a valid image.")

    h, w = img.shape[:2]
    ok = False
    if h <= _WEBP_MAX_DIMENSION and w <= _WEBP_MAX_DIMENSION:
        ok, buf = _cv2.imencode('.webp', img, [_cv2.IMWRITE_WEBP_QUALITY, 90])
    if not ok:
        ok, buf = _cv2.imencode('.png', img)
        if not ok:
            raise ValueError(f"Failed to encode screenshot for {source_url!r} as WebP or PNG.")
        print(
            f"[Warning] Screenshot for {source_url!r} ({w}x{h}) exceeds WebP's "
            f"{_WEBP_MAX_DIMENSION}px dimension limit (or WebP encoding failed); "
            f"saved as PNG bytes under {output_path.name}.",
            flush=True,
        )
    output_path.write_bytes(buf.tobytes())


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
    const isDate = /\\b\\d{4}[-/.]\\d{2}[-/.]\\d{2}\\b/.test(text) || /\\b\\d{2}[-/.]\\d{2}[-/.]\\d{4}\\b/.test(text);
    const isTime = /^\\d{1,2}:\\d{2}(:\\d{2})?\\s*(am|pm)?$/i.test(text);
    const isPrice = /^[\\$\\u00A3\\u00A5\\u20AC\\u20A1-\\u20CF]\\s*\\d+(?:\\.\\d{2})?$/i.test(text) || /^\\d+(?:\\.\\d{2})?\\s*(USD|EUR|CNY|MYR)$/i.test(text);
    
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

_CAPTURE_DOM_SNAPSHOT_JS = """
(() => {
  const TRACKED_TAGS = ['div','span','p','a','button','input','select','textarea',
    'img','video','iframe','form','nav','header','footer','main','section',
    'article','aside','h1','h2','h3','h4','h5','h6','ul','ol','li','table',
    'tr','td','th','label','svg','canvas'];
  const tagCounts = {};
  TRACKED_TAGS.forEach(t => { tagCounts[t] = 0; });
  let totalElements = 0;
  let totalDepth = 0;
  let hasForm = false;
  let hasImg = false;
  let hasVideo = false;
  let hasIframe = false;
  let interactiveCount = 0;
  const elements = [];

  function getDepth(el) {
    let depth = 0;
    let cur = el;
    while (cur.parentElement) { depth++; cur = cur.parentElement; }
    return depth;
  }

  document.querySelectorAll('*').forEach(el => {
    const tag = el.tagName.toLowerCase();
    if (TRACKED_TAGS.includes(tag)) {
      tagCounts[tag] = (tagCounts[tag] || 0) + 1;
    }
    totalElements++;
    totalDepth += getDepth(el);
    if (tag === 'form') hasForm = true;
    if (tag === 'img' || tag === 'video') hasImg = true;
    if (tag === 'video') hasVideo = true;
    if (tag === 'iframe') hasIframe = true;
    if (['button','a','input','select','textarea'].includes(tag)) interactiveCount++;

    const TARGET_TAGS = ['p','span','a','button','input','select','textarea','img','video','h1','h2','h3','h4','h5','h6','label','code','pre','svg','canvas','li','div','section'];
    if (TARGET_TAGS.includes(tag)) {
      const r = el.getBoundingClientRect();
      if (r.width > 2 && r.height > 2) {
        const entry = {
          tag: tag,
          x: Math.round(r.left + window.scrollX),
          y: Math.round(r.top + window.scrollY),
          w: Math.round(r.width),
          h: Math.round(r.height)
        };
        // A stable id/class attribute identifies the same DOM node across
        // baseline and current far more reliably than proximity + size ever
        // can — real pages assign ids/classes precisely so re-renders and
        // reflows can still be tracked as "the same element". Only recorded
        // when non-empty so absence doesn't produce false matches.
        if (el.id) entry.eid = el.id;
        if (typeof el.className === 'string' && el.className.trim()) entry.ecls = el.className.trim();
        const TEXT_TAGS = ['p','span','a','button','h1','h2','h3','h4','h5','h6','label','code','pre','li'];
        if (TEXT_TAGS.includes(tag)) {
          try {
            const cs = window.getComputedStyle(el);
            entry.font = cs.fontFamily.split(',')[0].replace(/["']/g, '').trim();
            entry.color = cs.color;
            entry.bg = cs.backgroundColor;
            // scrollWidth/Height > client* means content overflows its box —
            // the DOM-level signature of clipped/truncated text.
            entry.sw = el.scrollWidth;
            entry.cw = el.clientWidth;
            // On a repeating list (story links, nav items) the text content
            // is a far more reliable identity signal than position: it
            // survives reflow when a sibling is removed/reordered, whereas
            // every position-based signal shifts for every item after the
            // change. Truncated so the snapshot payload stays small.
            const txt = (el.textContent || '').trim();
            if (txt) entry.txt = txt.slice(0, 60);
          } catch (e) { /* ignore */ }
        }
        elements.push(entry);
      }
    }
  });

  return {
    tag_counts: tagCounts,
    total_elements: totalElements,
    avg_depth: totalElements > 0 ? totalDepth / totalElements : 0,
    has_form: hasForm,
    has_img: hasImg,
    has_video: hasVideo,
    has_iframe: hasIframe,
    interactive_count: interactiveCount,
    elements: elements
  };
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
        locale_clean = cfg.locale.replace("_", "-")
        options["locale"] = locale_clean
        # Explicitly inject the Accept-Language HTTP header to force standard localized content delivery
        extra_headers = options.get("extra_http_headers", {})
        if "Accept-Language" not in extra_headers:
            lang_code = locale_clean.split("-")[0]
            extra_headers["Accept-Language"] = f"{locale_clean},{lang_code};q=0.9,en;q=0.8"
            options["extra_http_headers"] = extra_headers
    if cfg.timezone_id:
        options["timezone_id"] = cfg.timezone_id
    if cfg.color_scheme:
        options["color_scheme"] = cfg.color_scheme
    if cfg.extra_headers:
        # Merge other extra headers if present
        existing_headers = options.get("extra_http_headers", {})
        existing_headers.update(cfg.extra_headers)
        options["extra_http_headers"] = existing_headers
    return options


_THREAD_LOCAL = threading.local()

def set_shared_browser(playwright: Playwright | None, browser: Any) -> None:
    previous_playwright = getattr(_THREAD_LOCAL, "playwright", None)
    previous_browser = getattr(_THREAD_LOCAL, "browser", None)
    _THREAD_LOCAL.playwright = playwright
    _THREAD_LOCAL.browser = browser
    if playwright or browser:
        register_instances(playwright, browser)
    else:
        # Clearing the slot is how close_shared_browser() reports that it already
        # shut these down. Without dropping them from the registry they stay
        # there as closed handles, and the atexit sweep tries to close them a
        # second time against a driver process that no longer exists.
        unregister_instances(previous_playwright, previous_browser)

class SessionCache:
    """TTL cache for login states."""
    def __init__(self):
        self._cache = {}
        self._lock = threading.Lock()

    def get(self, login_url: str, username: str) -> dict | None:
        if not login_url:
            return None
        parsed = urlparse(login_url)
        key = (parsed.netloc, username)
        import time
        with self._lock:
            if key in self._cache:
                expiry, state = self._cache[key]
                if time.time() < expiry:
                    return state
                else:
                    del self._cache[key]
            return None

    def set(self, login_url: str, username: str, storage_state: dict, ttl_minutes: int = 30) -> None:
        if not login_url:
            return
        parsed = urlparse(login_url)
        key = (parsed.netloc, username)
        import time
        expiry = time.time() + (ttl_minutes * 60)
        with self._lock:
            self._cache[key] = (expiry, storage_state)

_session_cache = SessionCache()


class AdaptiveConcurrencyController:
    """Monitors system memory and CPU to dynamically scale concurrency."""
    def __init__(self):
        self.max_concurrency = 4
        self.last_check = 0.0
        self._lock = threading.Lock()

    def get_concurrency(self) -> int:
        import time
        import os
        now = time.time()
        with self._lock:
            if now - self.last_check > 30:
                self.last_check = now
                try:
                    import psutil
                    vm = psutil.virtual_memory()
                    free_gb = vm.available / (1024 ** 3)
                    cpu_percent = psutil.cpu_percent()
                    
                    cpu_count = os.cpu_count() or 4
                    if free_gb > 1.0:
                        self.max_concurrency = min(cpu_count, 16)
                    elif free_gb > 0.5:
                        self.max_concurrency = min(cpu_count, 8)
                    else:
                        self.max_concurrency = 4
                        
                    if cpu_percent > 85.0:
                        self.max_concurrency = max(2, self.max_concurrency - 1)
                except Exception:
                    cpu_count = os.cpu_count() or 4
                    self.max_concurrency = min(cpu_count, 8)
            return self.max_concurrency

_concurrency_controller = AdaptiveConcurrencyController()


class BrowserContextPool:
    """Pool of reusable browser contexts to avoid launching browser per page."""
    def __init__(self, browser_type_name: str = "chromium"):
        self.browser_type_name = browser_type_name
        self.pw = None
        self.browser = None
        self.contexts = []
        self._lock = asyncio.Lock()

    async def get_browser(self):
        async with self._lock:
            if not self.browser:
                from playwright.async_api import async_playwright
                self.pw = await async_playwright().start()
                b_type = getattr(self.pw, self.browser_type_name)
                self.browser = await b_type.launch(headless=True)
                register_instances(playwright=self.pw, browser=self.browser)
            return self.browser

    async def acquire_context(self, opts: dict) -> Any:
        browser = await self.get_browser()
        return await browser.new_context(**opts)

    async def close_all(self):
        async with self._lock:
            if self.browser:
                await self.browser.close()
                unregister_instances(browser=self.browser)
                self.browser = None
            if self.pw:
                await self.pw.stop()
                unregister_instances(playwright=self.pw)
                self.pw = None

_GLOBAL_CONTEXT_POOLS: dict[str, BrowserContextPool] = {}

async def get_global_context_pool(browser_type_name: str) -> BrowserContextPool:
    if browser_type_name not in _GLOBAL_CONTEXT_POOLS:
        _GLOBAL_CONTEXT_POOLS[browser_type_name] = BrowserContextPool(browser_type_name)
    return _GLOBAL_CONTEXT_POOLS[browser_type_name]


async def _async_perform_login(page: Any, context: Any, cfg: CaptureConfig) -> dict | None:
    login_url = getattr(cfg, "login_url", None)
    username_selector = getattr(cfg, "username_selector", None)
    password_selector = getattr(cfg, "password_selector", None)
    submit_selector = getattr(cfg, "submit_selector", None)
    login_username = getattr(cfg, "login_username", None)
    login_password = getattr(cfg, "login_password", None)
    
    try:
        username_selector = (username_selector or "").strip()
        password_selector = (password_selector or "").strip()
        submit_selector = (submit_selector or "").strip()

        # Scope auto-detected fallback selectors to the <form> that contains the
        # password field, so we don't fill/click an unrelated form on the login
        # page (e.g. a newsletter signup or search box) when nothing explicit is configured.
        search_root = page
        try:
            form_scope = page.locator('form:has(input[type="password"])').first
            if await form_scope.count() > 0:
                search_root = form_scope
        except Exception:
            pass

        if not username_selector:
            for sel in [
                'input[type="email"]',
                'input[name*="username" i]',
                'input[name*="email" i]',
                'input[name*="login" i]',
                'input[id*="username" i]',
                'input[id*="email" i]',
                'input[id*="login" i]',
                'input[type="text"]'
            ]:
                try:
                    if await search_root.locator(sel).first.is_visible(timeout=500):
                        username_selector = sel
                        break
                except Exception:
                    pass
            if not username_selector:
                username_selector = 'input[type="text"]'

        if not password_selector:
            for sel in [
                'input[type="password"]',
                'input[name*="password" i]',
                'input[id*="password" i]'
            ]:
                try:
                    if await search_root.locator(sel).first.is_visible(timeout=500):
                        password_selector = sel
                        break
                except Exception:
                    pass
            if not password_selector:
                password_selector = 'input[type="password"]'

        if not submit_selector:
            for sel in [
                'button[type="submit"]',
                'input[type="submit"]',
                'button:has-text("Login")',
                'button:has-text("Sign in")',
                'button:has-text("登录")',
                'button:has-text("Submit")',
                'button',
                'input[type="button"]'
            ]:
                try:
                    if await search_root.locator(sel).first.is_visible(timeout=500):
                        submit_selector = sel
                        break
                except Exception:
                    pass
            if not submit_selector:
                submit_selector = 'button'

        await search_root.locator(username_selector).first.fill(login_username or "")
        await search_root.locator(password_selector).first.fill(login_password or "")

        try:
            async with page.expect_navigation(wait_until="networkidle", timeout=15000):
                await search_root.locator(submit_selector).first.click()
        except Exception:
            await search_root.locator(submit_selector).first.click()
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                await page.wait_for_timeout(1000)
            
        state = await context.storage_state()
        return state
    except Exception as e:
        print(f"[LOGIN ERROR] Async login failed at {login_url}: {e}")
        return None


async def _async_capture_one_with_pool(
    cfg: CaptureConfig,
    output_path: Path,
) -> tuple[Path, list, Exception | None]:
    try:
        pool = await get_global_context_pool(cfg.browser or "chromium")
        await pool.get_browser()
        
        opts: dict = {}
        if cfg.device:
            devices = pool.pw.devices if pool.pw else {}
            if cfg.device in devices:
                opts.update(devices[cfg.device])
        else:
            opts["viewport"] = {"width": cfg.viewport[0], "height": cfg.viewport[1]}
        if cfg.locale:
            locale_clean = cfg.locale.replace("_", "-")
            opts["locale"] = locale_clean
            # Force Accept-Language HTTP header matching the chosen locale
            extra_headers = opts.get("extra_http_headers", {})
            if "Accept-Language" not in extra_headers:
                lang_code = locale_clean.split("-")[0]
                extra_headers["Accept-Language"] = f"{locale_clean},{lang_code};q=0.9,en;q=0.8"
                opts["extra_http_headers"] = extra_headers
        if cfg.timezone_id:
            opts["timezone_id"] = cfg.timezone_id
        if cfg.color_scheme:
            opts["color_scheme"] = cfg.color_scheme
        if cfg.extra_headers:
            existing_headers = opts.get("extra_http_headers", {})
            existing_headers.update(cfg.extra_headers)
            opts["extra_http_headers"] = existing_headers

        login_url = getattr(cfg, "login_url", None)
        login_username = getattr(cfg, "login_username", None)
        if login_url and login_username:
            cached_state = _session_cache.get(login_url, login_username)
            if cached_state:
                opts["storage_state"] = cached_state
            else:
                browser = await pool.get_browser()
                temp_context = await browser.new_context()
                try:
                    page = await temp_context.new_page()
                    await page.goto(login_url, wait_until="networkidle", timeout=cfg.navigation_timeout_ms)
                    state = await _async_perform_login(page, temp_context, cfg)
                    if state:
                        _session_cache.set(login_url, login_username, state)
                        opts["storage_state"] = state
                finally:
                    await temp_context.close()

        context = await pool.acquire_context(opts)
        try:
            page = await context.new_page()
            if cfg.mock_routes:
                import json as _json
                for pattern, response in cfg.mock_routes.items():
                    async def make_async_handler(data):
                        async def _handler(route):
                            await route.fulfill(
                                status=200,
                                headers={"content-type": "application/json"},
                                body=_json.dumps(data) if isinstance(data, (dict, list)) else str(data)
                            )
                        return _handler
                    await page.route(pattern, await make_async_handler(response))

            try:
                await page.goto(cfg.url, wait_until=cfg.wait_until or "networkidle", timeout=cfg.navigation_timeout_ms)
            except Exception as e:
                if "timeout" in str(e).lower():
                    print(f"[Async Warning] Navigation timeout on {cfg.url}. Proceeding anyway.")
                else:
                    raise

            if cfg.disable_animations:
                await page.add_style_tag(content=_DISABLE_ANIMATION_CSS)
            if cfg.wait_for_selector:
                await page.wait_for_selector(cfg.wait_for_selector, timeout=cfg.navigation_timeout_ms)
            if cfg.wait_ms > 0:
                await page.wait_for_timeout(cfg.wait_ms)

            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                await page.wait_for_timeout(300)
                await page.evaluate("window.scrollTo(0, 0);")
                await page.wait_for_timeout(200)
            except Exception as exc:
                logger.debug("[Async Capture] Lazy-load scroll trigger failed for %s: %s", cfg.url, exc)

            try:
                await page.evaluate("document.fonts.ready")
            except Exception as exc:
                logger.debug("[Async Capture] Waiting for document.fonts.ready failed for %s: %s", cfg.url, exc)

            await page.evaluate(_PREPARE_PAGE_JS)

            dynamic_regions: list = []
            try:
                dynamic_regions = await page.evaluate(_FIND_DYNAMIC_REGIONS_JS) or []
            except Exception as exc:
                logger.debug("[Async Capture] Dynamic region detection failed for %s: %s", cfg.url, exc)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            img_bytes = await page.screenshot(full_page=cfg.full_page)
            _encode_and_write_screenshot(img_bytes, output_path, cfg.url)

            try:
                dom_snapshot = await page.evaluate(_CAPTURE_DOM_SNAPSHOT_JS)
                if dom_snapshot:
                    import json as _json
                    dom_path = output_path.with_suffix('.dom.json')
                    dom_path.write_text(_json.dumps(dom_snapshot, separators=(',', ':')), encoding='utf-8')
            except Exception as exc:
                logger.debug("[Async Capture] DOM snapshot capture failed for %s: %s", cfg.url, exc)

            return output_path, dynamic_regions, None
        finally:
            await context.close()
    except Exception as exc:
        return output_path, [], exc

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

import atexit

_ALL_PLAYWRIGHT_INSTANCES = []
_ALL_BROWSER_INSTANCES = []
_INSTANCES_LOCK = threading.Lock()

def register_instances(playwright: Any | None = None, browser: Any | None = None) -> None:
    with _INSTANCES_LOCK:
        if playwright and playwright not in _ALL_PLAYWRIGHT_INSTANCES:
            _ALL_PLAYWRIGHT_INSTANCES.append(playwright)
        if browser and browser not in _ALL_BROWSER_INSTANCES:
            _ALL_BROWSER_INSTANCES.append(browser)

def unregister_instances(playwright: Any | None = None, browser: Any | None = None) -> None:
    with _INSTANCES_LOCK:
        if playwright and playwright in _ALL_PLAYWRIGHT_INSTANCES:
            _ALL_PLAYWRIGHT_INSTANCES.remove(playwright)
        if browser and browser in _ALL_BROWSER_INSTANCES:
            _ALL_BROWSER_INSTANCES.remove(browser)

# Nothing reached from the atexit handler may block shutdown without bound.
# Closing a Playwright object talks to its driver subprocess, and that process
# can already be gone by the time interpreter shutdown runs — awaiting a reply
# that will never arrive parks the process in select() with no way out. This
# was observed on Linux CI as a job that sat until the 6h ceiling with all of
# its actual work long finished.
_CLOSE_TIMEOUT_SECONDS = 10


def _instance_is_live(instance) -> bool:
    """Best-effort check for a handle worth closing.

    Treats anything that cannot answer as live, so an unfamiliar object still
    gets its close attempted (under the timeout) rather than being skipped.
    """
    is_connected = getattr(instance, "is_connected", None)
    if is_connected is None:
        return True
    try:
        return bool(is_connected())
    except Exception:
        return False


def _close_instance(instance, method_name):
    import inspect
    import asyncio
    method = getattr(instance, method_name, None)
    if not method:
        return
    if method_name == "close" and not _instance_is_live(instance):
        return
    try:
        if inspect.iscoroutinefunction(method):
            # asyncio.get_event_loop() was deprecated for this use: outside a
            # running loop it warns today and raises from 3.14 on. Ask for the
            # running loop explicitly and fall back to a fresh one, which is the
            # same pair of paths the old code reached via its except branch.
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            try:
                if loop is not None:
                    # Another thread owns the loop; hand the close off to it.
                    asyncio.run_coroutine_threadsafe(method(), loop)
                else:
                    asyncio.run(asyncio.wait_for(method(), _CLOSE_TIMEOUT_SECONDS))
            except Exception:
                pass
        else:
            method()
    except Exception:
        pass

def _close_shared_browser_at_exit():
    # Close thread-local browser if any on main thread
    local_playwright = getattr(_THREAD_LOCAL, "playwright", None)
    local_browser = getattr(_THREAD_LOCAL, "browser", None)
    # Routed through _close_instance so these get the same liveness check and
    # bounded wait as the registry sweep below, rather than calling straight
    # into a driver that may no longer be there.
    if local_browser:
        _close_instance(local_browser, "close")
    if local_playwright:
        _close_instance(local_playwright, "stop")
            
    # Clean up all globally tracked instances (across threads/pools)
    with _INSTANCES_LOCK:
        for browser in list(_ALL_BROWSER_INSTANCES):
            _close_instance(browser, "close")
        _ALL_BROWSER_INSTANCES.clear()
        
        for p in list(_ALL_PLAYWRIGHT_INSTANCES):
            _close_instance(p, "stop")
        _ALL_PLAYWRIGHT_INSTANCES.clear()

atexit.register(_close_shared_browser_at_exit)


def capture_website(
    cfg: CaptureConfig,
    output_path: Path,
    playwright_instance: Playwright | None = None,
    browser_instance: Any = None,
) -> List[Dict[str, Any]]:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    local_playwright = getattr(_THREAD_LOCAL, "playwright", None)
    local_browser = getattr(_THREAD_LOCAL, "browser", None)

    if local_browser and not local_browser.is_connected():
        logger.warning("[Playwright Pool] Shared browser crashed or disconnected. Re-initializing...")
        try:
            local_browser.close()
        except Exception:
            pass
        unregister_instances(browser=local_browser)
        _THREAD_LOCAL.browser = None
        local_browser = None

    if not playwright_instance and (not local_playwright or not local_browser):
        from playwright.sync_api import sync_playwright
        if not local_playwright:
            logger.info("[Playwright Pool] Initializing lazy thread-local playwright...")
            _THREAD_LOCAL.playwright = sync_playwright().start()
            local_playwright = _THREAD_LOCAL.playwright
            register_instances(playwright=local_playwright)
        logger.info("[Playwright Pool] Initializing lazy thread-local browser...")
        b_name = cfg.browser if cfg.browser in {"chromium", "firefox", "webkit"} else "chromium"
        b_type = getattr(local_playwright, b_name)
        _THREAD_LOCAL.browser = b_type.launch(headless=True)
        local_browser = _THREAD_LOCAL.browser
        register_instances(browser=local_browser)

    playwright_instance = playwright_instance or local_playwright
    browser_instance = browser_instance or local_browser

    if playwright_instance and browser_instance:
        opts = _build_context_options(playwright_instance, cfg)
        session_state = _perform_login_and_get_state(playwright_instance, browser_instance, cfg)
        if session_state:
            opts["storage_state"] = session_state
        context = browser_instance.new_context(**opts)
        try:
            page = context.new_page()
            dynamic_regions = _capture_page(page, cfg, output_path)
            return dynamic_regions
        finally:
            context.close()
    else:
        raise RuntimeError("[Playwright Pool] Failed to acquire browser instance.")


def _capture_page(page: Any, cfg: CaptureConfig, output_path: Path) -> List[Dict[str, Any]]:
    if cfg.mock_routes:
        _setup_routing_mocks(page, cfg.mock_routes)
    # 3-attempt navigation retry loop for transient network glitches
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            page.goto(cfg.url, wait_until=cfg.wait_until or "load", timeout=cfg.navigation_timeout_ms)
            break  # Success, exit retry loop
        except Exception as e:
            if "timeout" in str(e).lower():
                print(f"[Warning] Navigation timeout on {cfg.url} (Attempt {attempt}/{max_retries}). Proceeding to capture screenshot anyway.", flush=True)
                break  # For timeout, we proceed to screenshot anyway
            if attempt == max_retries:
                raise e  # Fail on the final attempt
            print(f"[Warning] Navigation failed on {cfg.url} (Attempt {attempt}/{max_retries}): {e}. Retrying in 2 seconds...", flush=True)
            page.wait_for_timeout(2000)

    # Implicit/Silent Auto-Login Detection using environment credentials
    import os
    env_username = os.environ.get("AUTO_LOGIN_USERNAME")
    env_password = os.environ.get("AUTO_LOGIN_PASSWORD")
    if env_username and env_password:
        try:
            has_pwd = False
            try:
                has_pwd = page.locator('input[type="password"]').first.is_visible(timeout=1000)
            except Exception as exc:
                logger.debug("[AUTO-LOGIN] Password field visibility check failed on %s: %s", page.url, exc)
            if has_pwd:
                print(f"[AUTO-LOGIN] Redirected or login form detected on {page.url}. Attempting automatic login...", flush=True)

                # Scope the fallback selector search to the <form> that actually contains
                # the detected password field, so we don't fill/click into an unrelated
                # form elsewhere on the page (e.g. a search box) when no explicit
                # username/submit selector is configured.
                search_root = page
                try:
                    form_scope = page.locator('form:has(input[type="password"])').first
                    if form_scope.count() > 0:
                        search_root = form_scope
                except Exception:
                    pass

                username_sel = None
                for sel in [
                    'input[type="email"]',
                    'input[name*="username" i]',
                    'input[name*="email" i]',
                    'input[name*="login" i]',
                    'input[id*="username" i]',
                    'input[id*="email" i]',
                    'input[type="text"]'
                ]:
                    try:
                        if search_root.locator(sel).first.is_visible(timeout=200):
                            username_sel = sel
                            print(f"[AUTO-LOGIN] Auto-detected username selector: {sel}", flush=True)
                            break
                    except Exception:
                        pass
                if not username_sel:
                    username_sel = 'input[type="text"]'

                password_sel = 'input[type="password"]'

                submit_sel = None
                for sel in [
                    'button[type="submit"]',
                    'input[type="submit"]',
                    'button:has-text("Login")',
                    'button:has-text("Sign in")',
                    'button:has-text("登录")',
                    'button',
                    'input[type="button"]'
                ]:
                    try:
                        if search_root.locator(sel).first.is_visible(timeout=200):
                            submit_sel = sel
                            print(f"[AUTO-LOGIN] Auto-detected submit selector: {sel}", flush=True)
                            break
                    except Exception:
                        pass
                if not submit_sel:
                    submit_sel = 'button'

                search_root.locator(username_sel).first.fill(env_username)
                search_root.locator(password_sel).first.fill(env_password)
                search_root.locator(submit_sel).first.click()
                
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                print("[AUTO-LOGIN] Automatic login successful! Continuing page capture.", flush=True)
        except Exception as login_err:
            print(f"[AUTO-LOGIN Warning] Automatic login check failed: {login_err}", flush=True)

    if cfg.disable_animations:
        page.add_style_tag(content=_DISABLE_ANIMATION_CSS)

    # Hide dynamic elements specified in the configuration to prevent false positives
    if getattr(cfg, "hide_selectors", None):
        for selector in cfg.hide_selectors:
            if selector.strip():
                try:
                    page.add_style_tag(content=f"{selector.strip()} {{ display: none !important; }}")
                    print(f"[Element Hide] Hidden selector: {selector.strip()}", flush=True)
                except Exception as hide_err:
                    print(f"[Element Hide Warning] Failed to hide selector {selector.strip()}: {hide_err}", flush=True)

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
    except Exception as exc:
        logger.debug("[Capture] Lazy-load scroll trigger failed for %s: %s", cfg.url, exc)

    # Wait for custom fonts to load fully
    try:
        page.evaluate("document.fonts.ready")
    except Exception as exc:
        logger.debug("[Capture] Waiting for document.fonts.ready failed for %s: %s", cfg.url, exc)

    page.evaluate(_PREPARE_PAGE_JS)
    dynamic_regions = []
    try:
        dynamic_regions = page.evaluate(_FIND_DYNAMIC_REGIONS_JS) or []
    except Exception as exc:
        logger.debug("[Capture] Dynamic region detection failed for %s: %s", cfg.url, exc)
    img_bytes = page.screenshot(full_page=cfg.full_page)
    _encode_and_write_screenshot(img_bytes, output_path, cfg.url)

    # Capture DOM snapshot for multimodal AI training (F proposal)
    try:
        dom_snapshot = page.evaluate(_CAPTURE_DOM_SNAPSHOT_JS)
        if dom_snapshot:
            dom_path = output_path.with_suffix('.dom.json')
            import json as _json
            dom_path.write_text(_json.dumps(dom_snapshot, separators=(',', ':')), encoding='utf-8')
    except Exception as e:
        print(f"[Error] Failed to capture DOM snapshot: {e}", flush=True)

    # Capture Web Vitals for performance budget (Task 16)
    try:
        perf_data = page.evaluate("""() => {
            const t = performance.getEntriesByType("navigation")[0] || {};
            const vitals = {
                ttfb: t.responseStart - t.requestStart,
                dom_interactive: t.domInteractive,
                dom_complete: t.domComplete,
                load_event: t.loadEventEnd,
                duration: t.duration,
            };
            return vitals;
        }""")
        if perf_data:
            perf_path = output_path.with_suffix('.perf.json')
            import json as _json
            perf_path.write_text(_json.dumps(perf_data, indent=2), encoding='utf-8')
    except Exception as exc:
        logger.debug("[Capture] Web Vitals capture failed for %s: %s", cfg.url, exc)

    return dynamic_regions


def _normalized_same_domain_href(
    base_url: str, 
    href: str, 
    domain: str, 
    preserve_query: bool = False,
    path_prefix: str | None = None
) -> str | None:
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

    # Path prefix restriction (e.g. keep crawler inside /cn/ subdirectory)
    if path_prefix:
        candidate_path = parsed.path.rstrip("/")
        prefix_clean = path_prefix.rstrip("/")
        if not (candidate_path == prefix_clean or candidate_path.startswith(prefix_clean + "/")):
            return None

    query = parsed.query if preserve_query else ""
    if preserve_query and query:
        stable_query = urlencode(sorted(parse_qsl(query, keep_blank_values=True)))
        query = stable_query
    path = parsed.path.rstrip("/")
    normalized = parsed._replace(fragment="", query=query, path=path)
    return urlunparse(normalized)


def discover_same_domain_urls(cfg: CaptureConfig, page_limit: int = 30, preserve_query: bool = False) -> list[str]:
    page_limit = max(1, int(page_limit))
    discovered: list[str] = []
    seen: set[str] = set()
    start = urlparse(cfg.url)
    if start.scheme not in {"http", "https"} or not start.netloc:
        raise ValueError("Start URL must be a valid http/https URL")
    if cfg.browser not in {"chromium", "firefox", "webkit"}:
        raise ValueError("browser must be one of: chromium, firefox, webkit")
    start_query = start.query if preserve_query else ""
    if preserve_query and start_query:
        start_query = urlencode(sorted(parse_qsl(start_query, keep_blank_values=True)))
    start_path = start.path.rstrip("/")
    start_url = urlunparse(start._replace(fragment="", query=start_query, path=start_path))
    queue = deque([start_url])

    with sync_playwright() as playwright:
        browser_type = getattr(playwright, cfg.browser)
        browser = browser_type.launch(headless=True)
        try:
            opts = _build_context_options(playwright, cfg)
            session_state = _perform_login_and_get_state(playwright, browser, cfg)
            if session_state:
                opts["storage_state"] = session_state
            context = browser.new_context(**opts)
            try:
                page = context.new_page()
                
                # Block heavy assets to make crawler lightning fast
                def filter_route(route):
                    if route.request.resource_type in {"image", "stylesheet", "font", "media", "texttrack", "manifest"}:
                        route.abort()
                    else:
                        route.continue_()
                page.route("**/*", filter_route)

                crawl_errors = 0
                while queue and len(discovered) < page_limit:
                    current_url = queue.popleft()
                    if current_url in seen:
                        continue
                    seen.add(current_url)
                    try:
                        # Allow a reasonable time (15s) to load pages during discovery
                        page.goto(current_url, wait_until="domcontentloaded", timeout=min(15000, cfg.navigation_timeout_ms))
                        discovered.append(current_url)
                        
                        hrefs = page.eval_on_selector_all(
                            "a[href]",
                            "nodes => nodes.map(node => node.getAttribute('href')).filter(Boolean)",
                        )
                        path_prefix = start_path if (start_path and start_path != "/") else None
                        for href in hrefs:
                            normalized = _normalized_same_domain_href(
                                current_url, 
                                href, 
                                start.netloc, 
                                preserve_query=preserve_query,
                                path_prefix=path_prefix
                            )
                            if normalized and normalized not in seen and normalized not in queue:
                                queue.append(normalized)
                                if len(queue) + len(discovered) >= page_limit * 3:
                                    break
                    except Exception as exc:
                        crawl_errors += 1
                        print(f"[CRAWL WARN] Skipped {current_url}: {exc}")
                        continue

                if crawl_errors:
                    print(f"[CRAWL] {crawl_errors} page(s) skipped due to errors out of {len(seen)} visited.")
            finally:
                context.close()
        finally:
            browser.close()

    return discovered


async def _async_capture_one(
    cfg: CaptureConfig,
    output_path: Path,
    semaphore: asyncio.Semaphore,
    browser_type_name: str,
) -> tuple[Path, list, Exception | None]:
    """Capture one URL asynchronously inside a semaphore-bounded slot."""
    async with semaphore:
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as pw:
                browser_type = getattr(pw, browser_type_name)
                browser = await browser_type.launch(headless=True)
                try:
                    opts: dict = {}
                    if cfg.device:
                        devices = pw.devices
                        if cfg.device in devices:
                            opts.update(devices[cfg.device])
                    else:
                        opts["viewport"] = {"width": cfg.viewport[0], "height": cfg.viewport[1]}
                    if cfg.locale:
                        locale_clean = cfg.locale.replace("_", "-")
                        opts["locale"] = locale_clean
                        # Force Accept-Language HTTP header matching the chosen locale
                        extra_headers = opts.get("extra_http_headers", {})
                        if "Accept-Language" not in extra_headers:
                            lang_code = locale_clean.split("-")[0]
                            extra_headers["Accept-Language"] = f"{locale_clean},{lang_code};q=0.9,en;q=0.8"
                            opts["extra_http_headers"] = extra_headers
                    if cfg.timezone_id:
                        opts["timezone_id"] = cfg.timezone_id
                    if cfg.color_scheme:
                        opts["color_scheme"] = cfg.color_scheme
                    if cfg.extra_headers:
                        existing_headers = opts.get("extra_http_headers", {})
                        existing_headers.update(cfg.extra_headers)
                        opts["extra_http_headers"] = existing_headers

                    context = await browser.new_context(**opts)
                    try:
                        page = await context.new_page()
                        if cfg.mock_routes:
                            import json as _json
                            for pattern, response in cfg.mock_routes.items():
                                async def make_async_handler(data):
                                    async def _handler(route):
                                        await route.fulfill(
                                            status=200,
                                            headers={"content-type": "application/json"},
                                            body=_json.dumps(data) if isinstance(data, (dict, list)) else str(data)
                                        )
                                    return _handler
                                await page.route(pattern, await make_async_handler(response))

                        try:
                            await page.goto(cfg.url, wait_until=cfg.wait_until or "networkidle", timeout=cfg.navigation_timeout_ms)
                        except Exception as e:
                            if "timeout" in str(e).lower():
                                print(f"[Async Warning] Navigation timeout on {cfg.url}. Proceeding anyway.")
                            else:
                                raise

                        if cfg.disable_animations:
                            await page.add_style_tag(content=_DISABLE_ANIMATION_CSS)
                        if cfg.wait_for_selector:
                            await page.wait_for_selector(cfg.wait_for_selector, timeout=cfg.navigation_timeout_ms)
                        if cfg.wait_ms > 0:
                            await page.wait_for_timeout(cfg.wait_ms)

                        try:
                            await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                            await page.wait_for_timeout(300)
                            await page.evaluate("window.scrollTo(0, 0);")
                            await page.wait_for_timeout(200)
                        except Exception as exc:
                            logger.debug("[Async Capture] Lazy-load scroll trigger failed for %s: %s", cfg.url, exc)

                        try:
                            await page.evaluate("document.fonts.ready")
                        except Exception as exc:
                            logger.debug("[Async Capture] Waiting for document.fonts.ready failed for %s: %s", cfg.url, exc)

                        await page.evaluate(_PREPARE_PAGE_JS)

                        dynamic_regions: list = []
                        try:
                            dynamic_regions = await page.evaluate(_FIND_DYNAMIC_REGIONS_JS) or []
                        except Exception as exc:
                            logger.debug("[Async Capture] Dynamic region detection failed for %s: %s", cfg.url, exc)

                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        img_bytes = await page.screenshot(full_page=cfg.full_page)
                        _encode_and_write_screenshot(img_bytes, output_path, cfg.url)


                        # Save DOM snapshot sidecar
                        try:
                            dom_snapshot = await page.evaluate(_CAPTURE_DOM_SNAPSHOT_JS)
                            if dom_snapshot:
                                import json as _json
                                dom_path = output_path.with_suffix('.dom.json')
                                dom_path.write_text(_json.dumps(dom_snapshot, separators=(',', ':')), encoding='utf-8')
                        except Exception as exc:
                            logger.debug("[Async Capture] DOM snapshot capture failed for %s: %s", cfg.url, exc)

                        # Capture Web Vitals for performance budget (Task 16)
                        try:
                            perf_data = await page.evaluate("""() => {
                                const t = performance.getEntriesByType("navigation")[0] || {};
                                const vitals = {
                                    ttfb: t.responseStart - t.requestStart,
                                    dom_interactive: t.domInteractive,
                                    dom_complete: t.domComplete,
                                    load_event: t.loadEventEnd,
                                    duration: t.duration,
                                };
                                return vitals;
                            }""")
                            if perf_data:
                                perf_path = output_path.with_suffix('.perf.json')
                                import json as _json
                                perf_path.write_text(_json.dumps(perf_data, indent=2), encoding='utf-8')
                        except Exception as exc:
                            logger.debug("[Async Capture] Web Vitals capture failed for %s: %s", cfg.url, exc)

                        return output_path, dynamic_regions, None
                    finally:
                        await context.close()
                finally:
                    await browser.close()
        except Exception as exc:
            return output_path, [], exc


def capture_websites_parallel(
    configs_and_paths: list[tuple[CaptureConfig, Path]],
    max_concurrency: int = 4,
) -> list[tuple[Path, list, Exception | None]]:
    """Capture multiple URLs in parallel using async Playwright with context pooling."""
    if not configs_and_paths:
        return []

    adaptive_limit = _concurrency_controller.get_concurrency()
    concurrency = min(max_concurrency, adaptive_limit)

    async def _run_all():
        semaphore = asyncio.Semaphore(concurrency)
        total = len(configs_and_paths)
        completed = 0

        async def _bounded_capture(cfg, path):
            nonlocal completed
            async with semaphore:
                res = await _async_capture_one_with_pool(cfg, path)
                completed += 1
                import os
                port = os.environ.get("VRT_DASHBOARD_PORT")
                if port:
                    # This progress ping is fire-and-forget, but urlopen is
                    # blocking: called directly it stalls the whole event loop
                    # for up to its timeout on every capture, serialising work
                    # that is supposed to run concurrently. Hand it to a thread.
                    def _emit_progress():
                        import json as _json
                        import urllib.request
                        url = f"http://127.0.0.1:{port}/api/events/emit"
                        payload = {
                            "type": "capture_progress",
                            "data": {
                                "completed": completed,
                                "total": total,
                                "url": cfg.url,
                            }
                        }
                        req = urllib.request.Request(
                            url,
                            data=_json.dumps(payload).encode("utf-8"),
                            headers={"Content-Type": "application/json"}
                        )
                        with urllib.request.urlopen(req, timeout=1.0):
                            pass

                    try:
                        await asyncio.to_thread(_emit_progress)
                    except Exception:
                        pass
                return res
        
        tasks = [
            _bounded_capture(cfg, path)
            for cfg, path in configs_and_paths
        ]
        return await asyncio.gather(*tasks)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, _run_all())
            results = future.result()
    else:
        results = asyncio.run(_run_all())

    return list(results)
