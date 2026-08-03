# ADR 0002 — The static file router is mounted last

**Status:** accepted

## Context

`dashboard_server.py` was ~2600 lines holding the app, 62 routes, the
authorisation gates and assorted helpers. Splitting the routes into
`visual_regression/api/*.py` routers required deciding where each one is
included.

Most of them can be mounted anywhere. `api/files.py` cannot. Its last route is
the single-page-app fallback:

```python
@router.get("/{path_name:path}")
def get_frontend_fallback(path_name: str, ...):
```

FastAPI matches routes in registration order. That pattern matches *everything*,
including `/api/health`.

## Decision

`api/files.py` is included at the **end** of `dashboard_server.py`, after every
other route on the app. Every other router is included near the top with the
imports.

The constraint is stated in `api/files.py`'s module docstring, at its include
site, and enforced by a test:

```python
def test_no_api_route_is_registered_after_the_catch_all(self):
    paths = self._paths()
    after = [p for p in paths[paths.index("/{path_name:path}") + 1:]
             if p.startswith("/api")]
    assert after == []
```

## Consequences

- Anyone adding a router must include it *above* the `api/files` include. The
  test fails loudly if they do not.
- The failure mode this prevents is unusually nasty: the API would not error,
  it would return `index.html` with HTTP 200 for every endpoint. The client
  would fail with a JSON parse error pointing at the browser, nowhere near the
  cause.
- `/demo/styles.css` is likewise registered before `/demo/{file_path:path}`,
  because the specific route carries the CI colour-injection hook that makes the
  demo defect appear. The wildcard would serve the file unmodified and the
  demonstration would silently stop working.
