"""Static file serving: baselines, run artifacts, the demo portal and the SPA.

ORDERING MATTERS. The last route here is a catch-all (`/{path_name:path}`) that
serves the frontend, so this router must be included AFTER every other route in
the app. Included earlier it would match `/api/anything` first and shadow the
whole API.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse

from .deps import get_paths_dep, get_project_root_dep, require_authorized_client

router = APIRouter(tags=["files"])

_IMMUTABLE_CACHE = {"Cache-Control": "public, max-age=3600"}


def safe_path(base: Path, relative: str) -> Path:
    """Resolve `relative` under `base`, clamping anything that escapes.

    A traversal resolves to `base` itself, which is a directory, so the
    `.is_file()` check every caller performs then rejects it.
    """
    target = (base / relative).resolve()
    base_resolved = base.resolve()
    if base_resolved not in target.parents and target != base_resolved:
        return base_resolved
    return target


def _resolve_with_legacy_png(base: Path, relative: str) -> Path:
    """Resolve an artifact, falling back to .png for pre-WebP-migration captures."""
    resolved = safe_path(base, relative)
    if not resolved.is_file() and resolved.suffix == ".webp":
        legacy = resolved.with_suffix(".png")
        if legacy.is_file():
            return legacy
    return resolved


def _sniffed_image_type(path: Path) -> str | None:
    """The image type the bytes actually are, or None if not a known image.

    reporter.save_image encodes WebP and writes it to whatever path it was
    handed, so a stored file's extension says nothing about its encoding. Both
    directions occur in practice: baselines captured as `baseline.png` hold WebP
    bytes, and a full-page screenshot taller than WebP's 16383px limit falls back
    to PNG bytes under a `.webp` name.

    FileResponse derives Content-Type from the extension, so it was announcing
    the wrong type for either case. Browsers sniff and render it anyway, which is
    why this stayed invisible — but Content-Type is what every non-browser
    consumer trusts, and a header that contradicts the payload is worth more
    than a rendering bug: it is a claim the server makes and cannot support.
    """
    try:
        with path.open("rb") as handle:
            head = handle.read(12)
    except OSError:
        return None
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    return None


def _serve(path: Path, headers: dict | None = None) -> FileResponse:
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    kwargs = {}
    if headers:
        kwargs["headers"] = headers
    if path.suffix.lower() in {".png", ".webp", ".jpg", ".jpeg"}:
        sniffed = _sniffed_image_type(path)
        if sniffed:
            kwargs["media_type"] = sniffed
    return FileResponse(path, **kwargs)


@router.get("/baseline/{baseline_name}/{version_or_file:path}")
def get_baseline_file(
    baseline_name: str,
    version_or_file: str,
    paths=Depends(get_paths_dep),
    authorized=Depends(require_authorized_client),
):
    return _serve(
        _resolve_with_legacy_png(paths.baselines_dir, f"{baseline_name}/{version_or_file}"),
        _IMMUTABLE_CACHE,
    )


@router.get("/artifacts/{run_id}/{file_path:path}")
def get_artifact_file(
    run_id: str,
    file_path: str,
    paths=Depends(get_paths_dep),
    authorized=Depends(require_authorized_client),
):
    return _serve(
        _resolve_with_legacy_png(paths.runs_dir, f"{run_id}/{file_path}"),
        _IMMUTABLE_CACHE,
    )


@router.get("/demo/styles.css")
def get_demo_styles(project_root=Depends(get_project_root_dep)):
    # Intentional demo/CI hook, not debug leftovers: setting LENS_DEMO_CSS_INJECT=true
    # swaps the demo portal's brand color so a baseline captured beforehand shows a
    # real visual regression, letting us demonstrate/test the tool (and the CI
    # gatekeeper via `check-ci`) actually catching a color-regression defect.
    # Scoped tightly to this one route/file and one known CSS property so it can
    # never be used to inject arbitrary content into other served paths.
    css_path = project_root / "demo_portal" / "styles.css"
    if not css_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if os.environ.get("LENS_DEMO_CSS_INJECT") == "true":
        content = css_path.read_text(encoding="utf-8").replace(
            "--brand: #0f5f8f;", "--brand: #ef4444;"
        )
        return Response(content, media_type="text/css")
    return FileResponse(css_path)


@router.get("/demo/{file_path:path}")
def get_demo_file(file_path: str, project_root=Depends(get_project_root_dep)):
    return _serve(safe_path(project_root / "demo_portal", file_path))


@router.get("/assets/{file_path:path}")
def get_assets_file(file_path: str, project_root=Depends(get_project_root_dep)):
    frontend_dir = project_root / "dashboard_frontend" / "dist"
    return _serve(safe_path(frontend_dir / "assets", file_path))


@router.get("/{path_name:path}")
def get_frontend_fallback(path_name: str, project_root=Depends(get_project_root_dep)):
    """SPA fallback. Must stay the last route registered on the app."""
    # Without this, an unknown /api/... path would fall through to index.html and
    # the client would try to parse HTML as JSON.
    if path_name.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")

    frontend_dir = project_root / "dashboard_frontend" / "dist"
    resolved = safe_path(frontend_dir, path_name)
    if resolved.is_file():
        return FileResponse(resolved)

    fallback_index = frontend_dir / "index.html"
    if fallback_index.is_file():
        return FileResponse(fallback_index)
    raise HTTPException(status_code=404, detail="Frontend build missing. Run npm run build.")
