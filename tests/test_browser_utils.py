from visual_regression.browser import _normalized_same_domain_href


def test_normalized_same_domain_href_keeps_same_domain_and_strips_query():
    href = _normalized_same_domain_href(
        "https://example.com/products?page=1",
        "/pricing?ref=nav#top",
        "example.com",
    )
    assert href == "https://example.com/pricing"


def test_normalized_same_domain_href_rejects_external_links():
    href = _normalized_same_domain_href(
        "https://example.com",
        "https://other.com/page",
        "example.com",
    )
    assert href is None


def test_normalized_same_domain_href_can_preserve_query_parameters():
    href = _normalized_same_domain_href(
        "https://example.com/products?page=1",
        "/pricing?b=2&a=1#top",
        "example.com",
        preserve_query=True,
    )
    assert href == "https://example.com/pricing?a=1&b=2"


def test_clearing_shared_browser_unregisters_it_from_the_atexit_sweep():
    """A browser the caller already closed must leave the registry.

    close_shared_browser() reports the shutdown by calling
    set_shared_browser(None, None). If the handle stays registered, the atexit
    sweep closes it a second time against a driver process that is gone, and
    waits for a reply that never comes.
    """
    from visual_regression import browser as browser_mod

    sentinel_pw, sentinel_browser = object(), object()
    browser_mod.set_shared_browser(sentinel_pw, sentinel_browser)
    assert sentinel_browser in browser_mod._ALL_BROWSER_INSTANCES
    assert sentinel_pw in browser_mod._ALL_PLAYWRIGHT_INSTANCES

    browser_mod.set_shared_browser(None, None)

    assert sentinel_browser not in browser_mod._ALL_BROWSER_INSTANCES
    assert sentinel_pw not in browser_mod._ALL_PLAYWRIGHT_INSTANCES


def test_close_instance_skips_a_browser_that_is_already_disconnected():
    from visual_regression.browser import _close_instance

    calls = []

    class AlreadyClosed:
        def is_connected(self):
            return False

        def close(self):
            calls.append("close")

    _close_instance(AlreadyClosed(), "close")
    assert calls == []


def test_close_instance_gives_up_on_a_close_that_never_completes():
    """The await is bounded, so shutdown cannot park forever."""
    import asyncio
    import time

    from visual_regression import browser as browser_mod

    class NeverFinishes:
        def is_connected(self):
            return True

        async def close(self):
            await asyncio.sleep(3600)

    original = browser_mod._CLOSE_TIMEOUT_SECONDS
    browser_mod._CLOSE_TIMEOUT_SECONDS = 0.25
    try:
        started = time.monotonic()
        browser_mod._close_instance(NeverFinishes(), "close")
        elapsed = time.monotonic() - started
    finally:
        browser_mod._CLOSE_TIMEOUT_SECONDS = original

    assert elapsed < 30, f"close was not bounded by the timeout (took {elapsed:.1f}s)"
