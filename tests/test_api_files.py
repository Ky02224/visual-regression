"""Tests for static file resolution and the route ordering it depends on.

Two things here can fail quietly:

* `safe_path` is the containment check for three public file routes. If it ever
  stops clamping, `/artifacts/x/../../../etc/passwd` reads off the host.
* the SPA catch-all must remain the last route registered. FastAPI matches in
  order, so a router included after it would be unreachable and every API path
  below it would start returning index.html instead of JSON.
"""

from __future__ import annotations

import pytest

from visual_regression.api.files import _resolve_with_legacy_png, safe_path


class TestSafePath:
    def test_resolves_a_file_inside_the_base(self, tmp_path):
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        assert safe_path(tmp_path, "a.txt").name == "a.txt"

    def test_resolves_a_nested_file(self, tmp_path):
        (tmp_path / "runs").mkdir()
        (tmp_path / "runs" / "r.html").write_text("x", encoding="utf-8")
        assert safe_path(tmp_path, "runs/r.html").name == "r.html"

    def test_a_traversal_clamps_to_the_base(self, tmp_path):
        """Clamping to the base (a directory) is what makes the caller's
        .is_file() check reject it."""
        assert safe_path(tmp_path, "../../../etc/passwd") == tmp_path.resolve()

    def test_a_traversal_hidden_mid_path_clamps(self, tmp_path):
        assert safe_path(tmp_path, "runs/../../secret.txt") == tmp_path.resolve()

    def test_an_absolute_path_clamps(self, tmp_path):
        """pathlib's `/` discards the left side when the right is absolute, so
        this needs its own assertion rather than falling out of the `..` case."""
        assert safe_path(tmp_path, "/etc/passwd") == tmp_path.resolve()

    def test_the_clamped_result_is_a_directory_not_a_file(self, tmp_path):
        assert safe_path(tmp_path, "../../etc/passwd").is_dir()


class TestLegacyPngFallback:
    def test_prefers_the_webp_when_it_exists(self, tmp_path):
        (tmp_path / "baseline.webp").write_bytes(b"webp")
        (tmp_path / "baseline.png").write_bytes(b"png")
        assert _resolve_with_legacy_png(tmp_path, "baseline.webp").suffix == ".webp"

    def test_falls_back_to_png_for_pre_migration_captures(self, tmp_path):
        (tmp_path / "baseline.png").write_bytes(b"png")
        assert _resolve_with_legacy_png(tmp_path, "baseline.webp").suffix == ".png"

    def test_returns_the_webp_path_when_neither_exists(self, tmp_path):
        """The caller turns a non-file into a 404; it must not raise here."""
        assert _resolve_with_legacy_png(tmp_path, "missing.webp").suffix == ".webp"

    def test_does_not_fall_back_for_other_extensions(self, tmp_path):
        (tmp_path / "report.png").write_bytes(b"png")
        assert _resolve_with_legacy_png(tmp_path, "report.html").suffix == ".html"

    def test_a_traversal_is_still_clamped(self, tmp_path):
        assert _resolve_with_legacy_png(tmp_path, "../../x.webp") == tmp_path.resolve()


def _route_paths():
    """Registered route paths, in order, across FastAPI versions.

    Older versions flattened included routers straight into ``app.routes``.
    Newer ones (starlette 1.x) keep an ``_IncludedRouter`` wrapper with no
    ``.path``, so reading ``r.path`` off every entry raises AttributeError —
    which is exactly how this suite broke against the pinned versions while
    passing locally on older ones. Expand the wrappers instead of assuming
    either shape.
    """
    import visual_regression.dashboard_server as server

    def expand(routes):
        out = []
        for route in routes:
            if hasattr(route, "path"):
                out.append(route.path)
            elif hasattr(route, "original_router"):
                out.extend(expand(route.original_router.routes))
        return out

    return expand(server.app.routes)


class TestCatchAllDoesNotShadowTheApi:
    """The behaviour the ordering exists to produce.

    Asserted through the app rather than by introspecting the route table:
    that is what actually matters, and it does not depend on how a given
    FastAPI version happens to represent an included router.
    """

    @staticmethod
    def _client():
        from fastapi.testclient import TestClient

        import visual_regression.dashboard_server as server
        return TestClient(server.app, raise_server_exceptions=False)

    def test_an_api_route_is_not_served_the_spa_fallback(self):
        response = self._client().get("/api/health")
        assert response.status_code == 200
        assert "text/html" not in response.headers.get("content-type", "")
        assert response.json()

    def test_an_unknown_api_path_404s_instead_of_returning_html(self):
        """Falling through to index.html would surface as a JSON parse error in
        the browser, nowhere near the cause."""
        response = self._client().get("/api/definitely-not-a-route")
        assert response.status_code == 404
        assert "text/html" not in response.headers.get("content-type", "")

    def test_a_gated_api_route_still_rejects_rather_than_falling_through(self):
        """401/403 proves the route matched and its dependency ran; 200 with
        HTML would mean the catch-all answered instead."""
        response = self._client().get("/api/users")
        assert response.status_code in (401, 403)


class TestRouteOrdering:
    """Guards the reason api/files is mounted last rather than with the others."""

    def test_the_catch_all_is_the_last_route(self):
        assert _route_paths()[-1] == "/{path_name:path}"

    def test_no_api_route_is_registered_after_the_catch_all(self):
        """Any API route below the catch-all would be unreachable — the request
        would match /{path_name:path} first and be served index.html."""
        paths = _route_paths()
        after = [p for p in paths[paths.index("/{path_name:path}") + 1:] if p.startswith("/api")]
        assert after == []

    @pytest.mark.parametrize("route", [
        "/api/health", "/api/auth/login", "/api/users",
        "/api/scheduler/jobs", "/api/integrations", "/api/comments",
    ])
    def test_extracted_routers_are_still_mounted(self, route):
        assert route in _route_paths()

    def test_the_static_routes_come_before_the_catch_all(self):
        paths = _route_paths()
        catch_all = paths.index("/{path_name:path}")
        for route in ("/demo/styles.css", "/assets/{file_path:path}"):
            assert paths.index(route) < catch_all

    def test_the_specific_demo_css_route_precedes_the_demo_wildcard(self):
        """/demo/styles.css carries the CI colour-injection hook; the wildcard
        would serve the file unmodified and the demo defect would vanish."""
        paths = _route_paths()
        assert paths.index("/demo/styles.css") < paths.index("/demo/{file_path:path}")
