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
