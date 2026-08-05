from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

try:
    from typing import Protocol, runtime_checkable
except ImportError:  # pragma: no cover - Python < 3.8 safeguard
    from typing_extensions import Protocol, runtime_checkable  # type: ignore[assignment]

from .config import WorkspacePaths, resolve_image_path
from ._json_cache import JsonCache
from ._file_lock import FileLock, atomic_replace

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Storage backend protocol & implementations
# ---------------------------------------------------------------------------

@runtime_checkable
class StorageBackend(Protocol):
    """Protocol that all storage backends must implement.

    Concrete backends are expected to be *additive* — local filesystem state
    is always the primary source of truth; the backend acts as a remote
    mirror for durability and cross-machine access.
    """

    def upload(self, local_path: Path, remote_key: str) -> str:
        """Upload a local file to the remote store.

        Returns:
            A URL or URI string identifying the stored object.
        """
        ...

    def download(self, remote_key: str, local_path: Path) -> None:
        """Download a remote object to *local_path* (creating parent dirs as needed)."""
        ...

    def exists(self, remote_key: str) -> bool:
        """Return ``True`` if the remote object exists."""
        ...

    def delete(self, remote_key: str) -> None:
        """Delete a remote object (no-op if it does not exist)."""
        ...


class LocalStorageBackend:
    """No-op backend that keeps files on the local filesystem (default behavior).

    All methods are intentional no-ops — the ``BaselineManager`` already writes
    files locally, so this backend simply satisfies the :class:`StorageBackend`
    protocol without duplicating any work.
    """

    def upload(self, local_path: Path, remote_key: str) -> str:  # noqa: ARG002
        """No-op — file is already on disk."""
        return local_path.as_uri()

    def download(self, remote_key: str, local_path: Path) -> None:  # noqa: ARG002
        """No-op — files are already local."""

    def exists(self, remote_key: str) -> bool:  # noqa: ARG002
        """Always returns ``True`` — existence is checked by the caller on disk."""
        return True

    def delete(self, remote_key: str) -> None:  # noqa: ARG002
        """No-op — deletion is handled by :meth:`BaselineManager.delete_baseline`."""


class S3StorageBackend:
    """Amazon S3 / MinIO / GCS-compatible storage backend.

    Configuration is read from the following environment variables:

    * ``VISUAL_S3_BUCKET``        — required bucket name.
    * ``VISUAL_S3_PREFIX``        — optional object key prefix (default: ``"baselines"``)
    * ``AWS_ACCESS_KEY_ID``       — AWS / MinIO access key.
    * ``AWS_SECRET_ACCESS_KEY``   — AWS / MinIO secret key.
    * ``AWS_DEFAULT_REGION``      — AWS region (default: ``"us-east-1"``)
    * ``VISUAL_S3_ENDPOINT_URL``  — custom endpoint for MinIO / GCS (optional).

    Requires ``boto3`` to be installed. If ``boto3`` is missing the constructor
    raises :class:`ImportError`.
    """

    def __init__(
        self,
        bucket: str | None = None,
        prefix: str | None = None,
        endpoint_url: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        region_name: str | None = None,
    ) -> None:
        try:
            import boto3  # type: ignore[import]
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "boto3 is required for S3StorageBackend. "
                "Install it with: pip install boto3"
            ) from exc

        self._bucket = (
            bucket
            or os.environ.get("VISUAL_S3_BUCKET")
            or ""
        ).strip()
        if not self._bucket:
            raise ValueError(
                "S3 bucket name is required. Set VISUAL_S3_BUCKET env var or pass bucket=."
            )

        self._prefix = (
            prefix
            or os.environ.get("VISUAL_S3_PREFIX", "baselines")
        ).strip().rstrip("/")

        _endpoint = endpoint_url or os.environ.get("VISUAL_S3_ENDPOINT_URL")
        _access_key = aws_access_key_id or os.environ.get("AWS_ACCESS_KEY_ID")
        _secret_key = aws_secret_access_key or os.environ.get("AWS_SECRET_ACCESS_KEY")
        _region = region_name or os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

        session = boto3.Session(
            aws_access_key_id=_access_key,
            aws_secret_access_key=_secret_key,
            region_name=_region,
        )
        client_kwargs: Dict[str, Any] = {}
        if _endpoint:
            client_kwargs["endpoint_url"] = _endpoint

        self._client = session.client("s3", **client_kwargs)
        logger.info(
            "S3StorageBackend initialised: bucket=%s prefix=%s endpoint=%s",
            self._bucket,
            self._prefix,
            _endpoint or "(AWS default)",
        )

    def _full_key(self, remote_key: str) -> str:
        """Prepend the configured prefix to a remote key."""
        return f"{self._prefix}/{remote_key}" if self._prefix else remote_key

    def upload(self, local_path: Path, remote_key: str) -> str:
        """Upload *local_path* to S3 under *remote_key*.

        Returns:
            The ``s3://bucket/key`` URI of the uploaded object.
        """
        key = self._full_key(remote_key)
        self._client.upload_file(str(local_path), self._bucket, key)
        url = f"s3://{self._bucket}/{key}"
        logger.debug("S3 upload: %s -> %s", local_path, url)
        return url

    def download(self, remote_key: str, local_path: Path) -> None:
        """Download *remote_key* from S3 and save to *local_path*."""
        key = self._full_key(remote_key)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(self._bucket, key, str(local_path))
        logger.debug("S3 download: %s -> %s", key, local_path)

    def exists(self, remote_key: str) -> bool:
        """Return ``True`` if the object exists in S3."""
        import botocore.exceptions  # type: ignore[import]
        key = self._full_key(remote_key)
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except botocore.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise

    def delete(self, remote_key: str) -> None:
        """Delete *remote_key* from S3 (silent no-op if missing)."""
        import botocore.exceptions  # type: ignore[import]
        key = self._full_key(remote_key)
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
            logger.debug("S3 delete: %s", key)
        except botocore.exceptions.ClientError as exc:
            if exc.response["Error"]["Code"] not in ("404", "NoSuchKey"):
                raise


def get_storage_backend(
    force_local: bool = False,
) -> LocalStorageBackend | S3StorageBackend:
    """Factory that auto-detects the appropriate storage backend from env vars.

    Returns a :class:`S3StorageBackend` when ``VISUAL_S3_BUCKET`` is set and
    ``boto3`` is importable; otherwise falls back to :class:`LocalStorageBackend`.

    Args:
        force_local: If ``True``, always return a :class:`LocalStorageBackend`
                     regardless of environment variables.
    """
    if force_local:
        return LocalStorageBackend()

    bucket = os.environ.get("VISUAL_S3_BUCKET", "").strip()
    if not bucket:
        return LocalStorageBackend()

    try:
        import boto3  # noqa: F401  # type: ignore[import]
        backend = S3StorageBackend()
        logger.info("get_storage_backend: using S3StorageBackend (bucket=%s)", bucket)
        return backend
    except ImportError:
        logger.warning(
            "VISUAL_S3_BUCKET is set but boto3 is not installed — "
            "falling back to LocalStorageBackend."
        )
        return LocalStorageBackend()
    except Exception as exc:  # pragma: no cover
        logger.error(
            "Failed to initialise S3StorageBackend (%s) — "
            "falling back to LocalStorageBackend.",
            exc,
        )
        return LocalStorageBackend()



def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BaselineManager:
    """Manages baseline images and their associated metadata.

    By default all files are stored on the local filesystem. Pass a
    :class:`StorageBackend` instance (e.g. :class:`S3StorageBackend`) to
    replicate baseline images to a remote store. Metadata JSON files are
    always kept locally for fast reads.
    """

    def __init__(
        self,
        paths: WorkspacePaths,
        storage_backend: LocalStorageBackend | S3StorageBackend | None = None,
    ) -> None:
        self.paths = paths
        self.paths.ensure()
        # Default to local-only storage when no backend is provided.
        self._storage: LocalStorageBackend | S3StorageBackend = (
            storage_backend if storage_backend is not None else LocalStorageBackend()
        )
        _is_s3 = isinstance(self._storage, S3StorageBackend)
        logger.info(
            "BaselineManager initialised: backend=%s",
            "S3StorageBackend" if _is_s3 else "LocalStorageBackend",
        )

    @staticmethod
    def normalize_name(name: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", name.strip())
        safe = safe.strip("_.")
        if not safe:
            raise ValueError("Invalid baseline name. Use letters, numbers, dot, dash, underscore.")
        return safe

    def baseline_dir(self, name: str) -> Path:
        return self.paths.baselines_dir / self.normalize_name(name)

    def baseline_image_path(self, name: str) -> Path:
        """Canonical write target for a baseline image — always .webp."""
        return self.baseline_dir(name) / "baseline.webp"

    def resolve_baseline_image_path(self, name: str) -> Path:
        """Where the baseline image actually lives right now: prefers .webp,
        falls back to .png for baselines captured before the WebP migration."""
        return resolve_image_path(self.baseline_dir(name), "baseline")

    def metadata_path(self, name: str) -> Path:
        return self.baseline_dir(name) / "metadata.json"

    def versions_dir(self, name: str) -> Path:
        return self.baseline_dir(name) / "versions"

    def latest_version_manifest_path(self, name: str) -> Path:
        return self.versions_dir(name) / "manifest.json"

    def exists(self, name: str) -> bool:
        """Return ``True`` if the baseline image is available locally or on the remote backend.

        When the local file is absent and the backend is :class:`S3StorageBackend`,
        the remote object is checked and \u2014 if found \u2014 downloaded to the local cache
        so subsequent calls are fast.
        """
        local_path = self.resolve_baseline_image_path(name)
        if local_path.exists():
            return True

        if isinstance(self._storage, S3StorageBackend):
            local_path = self.baseline_image_path(name)
            remote_key = f"{self.normalize_name(name)}/baseline.webp"
            try:
                if self._storage.exists(remote_key):
                    logger.info(
                        "Baseline '%s' not in local cache; downloading from remote.", name
                    )
                    self._storage.download(remote_key, local_path)
                    return local_path.exists()
            except Exception as exc:  # pragma: no cover
                logger.warning("Remote existence check failed for '%s': %s", name, exc)

        return False

    def get_baseline_image(self, name: str) -> Path:
        """Return the local path to the baseline image, downloading from S3 if needed.

        This is the preferred way to obtain the image path when an S3 backend may
        be in use: it checks the local cache first and only contacts S3 when the
        file is missing locally.

        Raises:
            FileNotFoundError: If the baseline is not found locally or remotely.
        """
        local_path = self.resolve_baseline_image_path(name)
        if local_path.exists():
            return local_path

        if isinstance(self._storage, S3StorageBackend):
            local_path = self.baseline_image_path(name)
            remote_key = f"{self.normalize_name(name)}/baseline.webp"
            try:
                if self._storage.exists(remote_key):
                    logger.info("Downloading baseline '%s' from S3 cache.", name)
                    self._storage.download(remote_key, local_path)
                    if local_path.exists():
                        return local_path
            except Exception as exc:  # pragma: no cover
                logger.warning("S3 download for '%s' failed: %s", name, exc)

        raise FileNotFoundError(
            f"Baseline image not found for '{name}' locally or in remote storage."
        )


    def _archive_existing_baseline(self, name: str, previous_meta: Dict[str, Any]) -> None:
        baseline_image = self.resolve_baseline_image_path(name)
        metadata_file = self.metadata_path(name)
        if not baseline_image.exists() or not metadata_file.exists():
            return

        versions_dir = self.versions_dir(name)
        versions_dir.mkdir(parents=True, exist_ok=True)
        # Second-precision timestamps collide when two archives happen within
        # the same second (easy to trigger via rapid automated updates); a
        # colliding mkdir(exist_ok=True) would silently overwrite the earlier
        # archive's files instead of erroring, destroying that version's
        # history. Disambiguate with a numeric suffix until the name is free.
        base_stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        version_stamp = base_stamp
        suffix = 1
        while (versions_dir / version_stamp).exists():
            suffix += 1
            version_stamp = f"{base_stamp}-{suffix}"
        version_dir = versions_dir / version_stamp
        version_dir.mkdir(parents=True)

        # Preserve the archived copy's actual format (a legacy baseline stays
        # .png here — copying raw bytes under a .webp name would mislabel them).
        shutil.copy2(baseline_image, version_dir / f"baseline{baseline_image.suffix}")
        shutil.copy2(metadata_file, version_dir / "metadata.json")

        manifest_path = self.latest_version_manifest_path(name)
        manifest: List[Dict[str, Any]] = []
        if manifest_path.exists():
            manifest = list(JsonCache.read(manifest_path))  # list() copies so appending won't mutate cache
        manifest.append(
            {
                "version": version_stamp,
                "archived_at": _utc_now(),
                "source_updated_at": previous_meta.get("updated_at"),
                "source_created_at": previous_meta.get("created_at"),
            }
        )
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        JsonCache.clear(manifest_path)  # invalidate cache after write

        # ── 企业级 S3 历史版本容灾同步 ──
        if isinstance(self._storage, S3StorageBackend):
            name_norm = self.normalize_name(name)
            try:
                self._storage.upload(version_dir / "baseline.webp", f"{name_norm}/versions/{version_stamp}/baseline.webp")
                self._storage.upload(version_dir / "metadata.json", f"{name_norm}/versions/{version_stamp}/metadata.json")
                self._storage.upload(manifest_path, f"{name_norm}/versions/manifest.json")
                logger.info("Archived baseline version '%s' [%s] synced to remote S3.", name, version_stamp)
            except Exception as exc:
                logger.warning(
                    "Failed to upload archived baseline version '%s' to remote storage: %s",
                    name,
                    exc,
                )


    def save_from_image(self, name: str, source_image_path: Path, capture_meta: Dict[str, Any], ignore_regions: List[Dict[str, int]] | None = None) -> None:
        target_dir = self.baseline_dir(name)
        target_dir.mkdir(parents=True, exist_ok=True)

        # Preserve the source's actual format — copying raw bytes from a
        # legacy .png (or a WebP-oversized full-page capture that fell back
        # to .png) under a .webp name would mislabel them.
        source_suffix = source_image_path.suffix or ".webp"
        target_image = target_dir / f"baseline{source_suffix}"
        metadata_file = self.metadata_path(name)
        lock_path = target_dir / ".lock"

        # Use file lock to prevent concurrent modifications to the baseline
        with FileLock(lock_path, timeout=30.0):
            now = _utc_now()

            previous_meta: Dict[str, Any] = {}
            if metadata_file.exists():
                previous_meta = self.load_metadata(name)
                self._archive_existing_baseline(name, previous_meta)

            # Use atomic replace instead of copy to prevent partial writes
            # First copy to temp file, then atomically replace
            import tempfile
            with tempfile.NamedTemporaryFile(dir=target_dir, delete=False, suffix=source_suffix) as tmp:
                tmp_path = Path(tmp.name)
            shutil.copy2(source_image_path, tmp_path)
            atomic_replace(tmp_path, target_image)

            # Remove a stale baseline file left over under the other
            # extension (e.g. updating a legacy .png baseline with a fresh
            # .webp capture) so resolve_baseline_image_path() doesn't pick
            # up outdated content instead of the one we just wrote.
            for stale_ext in (".webp", ".png"):
                if stale_ext == target_image.suffix:
                    continue
                stale_path = target_dir / f"baseline{stale_ext}"
                if stale_path.exists():
                    stale_path.unlink()

            # capture_website() writes a .dom.json sidecar next to whatever
            # path it's given — for create-baseline that's a throwaway temp
            # file (see cli.py:_capture_and_save_baseline), so without this
            # the sidecar never reaches the final baseline directory and
            # every DOM-diff check silently has no baseline-side data to
            # compare against, regardless of how the current side looks.
            source_dom_path = source_image_path.with_suffix(".dom.json")
            if source_dom_path.exists():
                target_dom_path = target_dir / "baseline.dom.json"
                shutil.copy2(source_dom_path, target_dom_path)

            history = previous_meta.get("history", [])
            history.append(
                {
                    "timestamp": now,
                    "actor": capture_meta.get("updated_by") or capture_meta.get("reviewer") or "system",
                    "source": capture_meta.get("source", "capture"),
                    "url": capture_meta.get("url"),
                }
            )
            metadata = {
                "name": self.normalize_name(name),
                "created_at": previous_meta.get("created_at", now),
                "updated_at": now,
                "capture": capture_meta,
                # Chromium renders text differently per platform and font set, so
                # a baseline is only valid against runs from the same kind of
                # machine — a Windows-captured reference fails on a Linux runner
                # for reasons that have nothing to do with the page. Nothing
                # recorded where a baseline came from, which left that mismatch
                # undetectable until the diff images were opened. See
                # tests/test_baseline_provenance.py, which uses this to keep
                # dev-machine captures out of the committed set.
                "system": {
                    "platform": platform.system(),
                    "release": platform.release(),
                },
                "history": history[-25:],
            }
            if ignore_regions is not None:
                metadata["ignore_regions"] = ignore_regions
            elif "ignore_regions" in previous_meta:
                metadata["ignore_regions"] = previous_meta["ignore_regions"]

            metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            # Invalidate JSON cache for this metadata file
            JsonCache.clear(metadata_file)

            # Mirror the new baseline image to the remote backend (if configured).
            # Failures are logged but do not roll back the local write.
            if isinstance(self._storage, S3StorageBackend):
                remote_key = f"{self.normalize_name(name)}/baseline{target_image.suffix}"
                try:
                    url = self._storage.upload(target_image, remote_key)
                    logger.info("Baseline '%s' uploaded to remote: %s", name, url)
                except Exception as exc:  # pragma: no cover
                    logger.error(
                        "Failed to upload baseline '%s' to remote storage: %s",
                        name,
                        exc,
                    )

    def load_metadata(self, name: str) -> Dict[str, Any]:
        path = self.metadata_path(name)
        if not path.exists():
            raise FileNotFoundError(f"metadata not found for baseline '{name}'")
        return JsonCache.read(path)

    def save_ignore_regions(self, name: str, ignore_regions: List[Dict[str, int]]) -> None:
        baseline_name = self.normalize_name(name)
        metadata_file = self.metadata_path(baseline_name)
        if not metadata_file.exists():
            raise FileNotFoundError(f"metadata not found for baseline '{name}'")
        lock_path = self.baseline_dir(baseline_name) / ".lock"
        with FileLock(lock_path, timeout=10.0):
            metadata = self.load_metadata(baseline_name)
            metadata["ignore_regions"] = ignore_regions
            metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            JsonCache.clear(metadata_file)

    def save_ignore_css_selectors(self, name: str, css_selectors: List[str]) -> None:
        baseline_name = self.normalize_name(name)
        metadata_file = self.metadata_path(baseline_name)
        if not metadata_file.exists():
            raise FileNotFoundError(f"metadata not found for baseline '{name}'")
        lock_path = self.baseline_dir(baseline_name) / ".lock"
        with FileLock(lock_path, timeout=10.0):
            metadata = self.load_metadata(baseline_name)
            metadata["ignore_css_selectors"] = css_selectors
            metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            JsonCache.clear(metadata_file)

    @staticmethod
    def _load_baseline_item(child: Path) -> "Dict[str, Any] | None":
        """Load full metadata for a single baseline directory: name, capture
        info, history, and archived versions with hrefs. Designed for
        parallel execution — this is the single source of truth for both
        list_baselines() and the dashboard snapshot's per-run baseline index,
        so directory-walk/JSON-read logic isn't duplicated between them."""
        if not child.is_dir():
            return None
        image_path = resolve_image_path(child, "baseline")
        metadata_path = child / "metadata.json"
        if not image_path.exists() or not metadata_path.exists():
            return None
        try:
            data = JsonCache.read(metadata_path)
        except Exception:
            logger.warning("Baseline '%s' has unreadable metadata.json; hiding it from listings", child.name, exc_info=True)
            return None

        baseline_name = data.get("name", child.name)
        capture = data.get("capture", {})

        versions_manifest: List[Dict[str, Any]] = []
        manifest_path = child / "versions" / "manifest.json"
        if manifest_path.exists():
            try:
                versions_manifest = JsonCache.read(manifest_path)
            except Exception:
                logger.debug("Baseline '%s' has unreadable versions manifest; version history unavailable", child.name, exc_info=True)
                versions_manifest = []

        versions = []
        for version in reversed(versions_manifest):
            version_id = version.get("version")
            if not version_id:
                continue
            versions.append(
                {
                    **version,
                    "image_href": f"/baseline/{baseline_name}/versions/{version_id}/baseline.webp",
                    "metadata_href": f"/baseline/{baseline_name}/versions/{version_id}/metadata.json",
                }
            )

        return {
            "name": baseline_name,
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "capture": capture,
            "url": capture.get("url"),
            "browser": capture.get("browser"),
            "device": capture.get("device"),
            "locale": capture.get("locale"),
            "timezone_id": capture.get("timezone_id"),
            "viewport": capture.get("viewport"),
            "history": data.get("history", []),
            "thumbnail_href": f"/baseline/{baseline_name}/baseline.webp",
            "current_image_href": f"/baseline/{baseline_name}/baseline.webp",
            "metadata_href": f"/baseline/{baseline_name}/metadata.json",
            "versions": versions,
            "version_count": len(versions),
        }

    def list_baselines(self) -> List[Dict[str, Any]]:
        dirs = sorted(self.paths.baselines_dir.iterdir())
        # Use a thread pool to read multiple JSON files concurrently.
        # ThreadPoolExecutor.map preserves input order, so the result is still sorted.
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(self._load_baseline_item, dirs))
        return [r for r in results if r is not None]

    def list_baselines_indexed(self) -> Dict[str, Dict[str, Any]]:
        """Same data as list_baselines(), indexed by name for O(1) lookup
        (e.g. when matching runs to their baseline without re-scanning disk
        per run)."""
        return {item["name"]: item for item in self.list_baselines()}

    def get_baseline_details(self, name: str) -> Dict[str, Any]:
        baseline_name = self.normalize_name(name)
        data = self.load_metadata(baseline_name)
        versions_manifest: List[Dict[str, Any]] = []
        manifest_path = self.latest_version_manifest_path(baseline_name)
        if manifest_path.exists():
            versions_manifest = JsonCache.read(manifest_path)

        versions = []
        for version in reversed(versions_manifest):
            version_id = version.get("version")
            if not version_id:
                continue
            versions.append(
                {
                    **version,
                    "image_href": f"/baseline/{baseline_name}/versions/{version_id}/baseline.webp",
                    "metadata_href": f"/baseline/{baseline_name}/versions/{version_id}/metadata.json",
                }
            )

        return {
            "name": baseline_name,
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "capture": data.get("capture", {}),
            "ignore_regions": data.get("ignore_regions", []),
            "ignore_css_selectors": data.get("ignore_css_selectors", []),
            "custom_threshold_pct": data.get("custom_threshold_pct"),
            "history": data.get("history", []),
            "current_image_href": f"/baseline/{baseline_name}/baseline.webp",
            "metadata_href": f"/baseline/{baseline_name}/metadata.json",
            "versions": versions,
        }

    def save_custom_threshold(self, name: str, threshold_pct: float | None) -> None:
        target_dir = self.baseline_dir(name)
        metadata_file = self.metadata_path(name)
        lock_path = target_dir / ".lock"
        with FileLock(lock_path, timeout=30.0):
            if not metadata_file.exists():
                raise FileNotFoundError(f"metadata not found for baseline '{name}'")
            metadata = self.load_metadata(name)
            if threshold_pct is None:
                metadata.pop("custom_threshold_pct", None)
            else:
                metadata["custom_threshold_pct"] = float(threshold_pct)
            metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            JsonCache.clear(metadata_file)

    def check_and_rolling_update(self, name: str, current_image_path: Path, run_passed: bool) -> bool:
        """Check if we should automatically promote the current image to the baseline.
        We do this if the rolling strategy is enabled (e.g. VISUAL_ROLLING_BASELINE=true)
        and the run has passed.
        """
        rolling_enabled = os.environ.get("VISUAL_ROLLING_BASELINE", "false").lower() in ("true", "1", "yes")
        if rolling_enabled and run_passed and current_image_path.exists():
            capture_meta = {
                "updated_by": "rolling_system",
                "source": "rolling_baseline",
            }
            try:
                self.save_from_image(name, current_image_path, capture_meta)
                logger.info("[RollingBaseline] Automatically updated baseline for case '%s'", name)
                return True
            except Exception as e:
                logger.warning("[RollingBaseline] Failed to update rolling baseline: %s", e)
        return False

    def delete_baseline(self, name: str) -> Dict[str, Any]:
        baseline_name = self.normalize_name(name)
        target_dir = self.baseline_dir(baseline_name).resolve()
        baselines_root = self.paths.baselines_dir.resolve()
        if baselines_root not in target_dir.parents:
            raise ValueError("Refusing to delete a baseline outside the baselines directory")
        if not target_dir.exists():
            raise FileNotFoundError(f"Baseline '{baseline_name}' not found")
        shutil.rmtree(target_dir)
        return {"name": baseline_name, "deleted": True}

    def restore_version(self, name: str, version: str, restored_by: str | None = None) -> Dict[str, Any]:
        baseline_name = self.normalize_name(name)
        version_id = str(version).strip()
        if not version_id:
            raise ValueError("version is required")

        version_dir = self.versions_dir(baseline_name) / version_id
        version_image = resolve_image_path(version_dir, "baseline")
        version_metadata = version_dir / "metadata.json"
        if not version_image.exists() or not version_metadata.exists():
            raise FileNotFoundError(f"Version '{version_id}' not found for baseline '{baseline_name}'")

        target_dir = self.baseline_dir(baseline_name)
        lock_path = target_dir / ".lock"

        # Every other metadata mutator (save_from_image, save_ignore_regions,
        # save_custom_threshold) takes this same lock around its
        # read-modify-write of metadata.json; restore_version previously did
        # not, so it could race a concurrent mutation on the same baseline
        # and interleave two non-atomic write_text() calls into a truncated
        # or corrupted metadata.json.
        with FileLock(lock_path, timeout=30.0):
            current_meta = self.load_metadata(baseline_name)
            self._archive_existing_baseline(baseline_name, current_meta)

            # Restore under the version's own format (copying raw bytes under the
            # wrong extension would mislabel a legacy .png as .webp or vice versa),
            # and remove any stale current-baseline file left over under the other
            # extension so resolve_baseline_image_path() doesn't pick it up instead.
            for stale_ext in (".webp", ".png"):
                stale_path = target_dir / f"baseline{stale_ext}"
                if stale_path.exists() and stale_path.suffix != version_image.suffix:
                    stale_path.unlink()
            shutil.copy2(version_image, target_dir / f"baseline{version_image.suffix}")
            restored_meta = json.loads(version_metadata.read_text(encoding="utf-8"))
            now = _utc_now()
            history = current_meta.get("history", [])
            history.append(
                {
                    "timestamp": now,
                    "actor": restored_by or "system",
                    "source": "restore",
                    "url": restored_meta.get("capture", {}).get("url"),
                    "version": version_id,
                }
            )
            payload = {
                "name": baseline_name,
                "created_at": current_meta.get("created_at", restored_meta.get("created_at", now)),
                "updated_at": now,
                "capture": restored_meta.get("capture", {}),
                "history": history[-25:],
                "restored_from_version": version_id,
            }
            self.metadata_path(baseline_name).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {
            "name": baseline_name,
            "restored_version": version_id,
            "restored_by": restored_by or "system",
            "updated_at": now,
        }
