"""embedding_cache.py — Thread-safe LRU cache for image embeddings.

Caches ResNet50 (or any torchvision backbone) embeddings keyed by the
SHA-256 digest of the image file bytes, so the cache automatically
invalidates when the file content changes.

Persistence:
    The cache is saved to / loaded from
    ``.visual-regression/embedding_cache.pkl`` using :mod:`pickle`.

Thread safety:
    A :class:`threading.Lock` serialises all read/write operations so the
    cache can safely be used from multiple threads (e.g. the FastAPI
    server's async workers).

Usage::

    from visual_regression.embedding_cache import embedding_cache

    # Returns a torch.Tensor (cached or freshly computed)
    embedding = embedding_cache.get_or_compute(
        image_path=Path("baseline.png"),
        model=backbone,
        transform=my_transform,
        device="cpu",
    )

    # Inspect cache stats
    print(embedding_cache.info())

    # Wipe all cached entries
    embedding_cache.clear()
"""
from __future__ import annotations

import atexit
import hashlib
import logging
import os
import pickle
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Default path for the on-disk persistence file.
_DEFAULT_CACHE_PATH = Path(".visual-regression") / "embedding_cache.pkl"

# Maximum number of entries to keep in the LRU cache.
_DEFAULT_MAXSIZE = 500


class EmbeddingCache:
    """LRU cache for image embeddings with SHA-256 keying and disk persistence.

    Args:
        maxsize: Maximum number of embedding tensors to keep in memory.
        cache_path: Path to the ``.pkl`` persistence file.  The file is
            loaded on construction (if it exists) and flushed to disk every
            ``_save_every_n_misses`` cache misses (plus a best-effort flush
            on process exit), rather than on every single miss.

    Example::

        cache = EmbeddingCache(maxsize=200)
        emb = cache.get_or_compute(img_path, model, transform, device="cuda")
        print(cache.info())
    """

    def __init__(
        self,
        maxsize: int = _DEFAULT_MAXSIZE,
        cache_path: Path = _DEFAULT_CACHE_PATH,
    ) -> None:
        self._maxsize: int = maxsize
        self._cache_path: Path = cache_path
        # OrderedDict used as a manual LRU: most-recently used at the *end*.
        self._store: OrderedDict[str, Any] = OrderedDict()
        self._lock: threading.Lock = threading.Lock()
        self._pending: set[str] = set()
        self._condition: threading.Condition = threading.Condition(self._lock)
        self._file_hash_cache: Dict[str, tuple[float, int, str]] = {}
        self._hits: int = 0
        self._misses: int = 0
        # Batch disk writes: a full pickle dump + fsync on every single miss
        # serializes training/inference throughput behind disk I/O. Persist
        # every N misses instead, plus a best-effort flush on process exit.
        self._misses_since_save: int = 0
        self._save_every_n_misses: int = 20
        self._load_from_disk()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_or_compute(
        self,
        image_path: Path,
        model: Any,
        transform: Any,
        device: str = "cpu",
        backbone_name: str = "resnet50",
    ) -> Any:
        """Return a cached embedding tensor, computing it on a cache miss.

        The cache key includes the backbone_name to isolate different model architectures.
        """
        import torch as _torch
        image_path = Path(image_path)
        if not image_path.exists():
            raise FileNotFoundError(f"[EmbeddingCache] Image not found: {image_path}")

        raw_key = self.get_file_hash(image_path)
        cache_key = f"{raw_key}_{backbone_name}"

        with self._lock:
            # Wait if another thread is currently computing this key
            while cache_key in self._pending:
                self._condition.wait()

            if cache_key in self._store:
                self._store.move_to_end(cache_key)
                self._hits += 1
                logger.debug(
                    "[EmbeddingCache] HIT  key=%s  path=%s", cache_key[:8], image_path.name
                )
                cached_val = self._store[cache_key]
                if isinstance(cached_val, _torch.Tensor):
                    return cached_val.to(device).float()
                return cached_val

            # Register as pending computation
            self._pending.add(cache_key)

        # Cache miss — compute outside the lock to avoid blocking other threads.
        logger.debug(
            "[EmbeddingCache] MISS key=%s  path=%s", cache_key[:8], image_path.name
        )
        try:
            embedding = self._compute_embedding(image_path, model, transform, device)
            embedding_half = embedding.half()
        finally:
            with self._lock:
                self._pending.remove(cache_key)
                self._condition.notify_all()

        with self._lock:
            self._store[cache_key] = embedding_half
            self._store.move_to_end(cache_key)
            self._misses += 1
            # Evict the oldest entry if over capacity.
            while len(self._store) > self._maxsize:
                evicted_key, _ = self._store.popitem(last=False)
                logger.debug("[EmbeddingCache] EVICT key=%s", evicted_key[:8])

        self._maybe_save_to_disk()
        return embedding.to(device)

    def get_or_compute_array(
        self,
        array: Any,
        model: Any,
        device: str = "cpu",
        backbone_name: str = "resnet50",
    ) -> Any:
        """Return a cached embedding tensor for a numpy image crop array, computing it on a cache miss."""
        import numpy as np
        import hashlib
        import torch as _torch
        from .ai_features import normalize_batch_uint8, ensure_rgb_batch

        contiguous = np.ascontiguousarray(array)
        raw_key = hashlib.sha256(contiguous.tobytes()).hexdigest()
        cache_key = f"{raw_key}_{backbone_name}"

        with self._lock:
            # Wait if another thread is currently computing this key
            while cache_key in self._pending:
                self._condition.wait()

            if cache_key in self._store:
                self._store.move_to_end(cache_key)
                self._hits += 1
                cached_val = self._store[cache_key]
                if isinstance(cached_val, _torch.Tensor):
                    return cached_val.to(device).float()
                return cached_val

            # Register as pending computation
            self._pending.add(cache_key)

        # Cache miss
        try:
            prepared = ensure_rgb_batch([array])
            normalized = normalize_batch_uint8(prepared)
            tensor = _torch.tensor(normalized, dtype=_torch.float32, device=device)

            model.eval()
            with _torch.no_grad():
                embedding = model(tensor).flatten(1).cpu()
            embedding_half = embedding.half()
        finally:
            with self._lock:
                self._pending.remove(cache_key)
                self._condition.notify_all()

        with self._lock:
            self._store[cache_key] = embedding_half
            self._store.move_to_end(cache_key)
            self._misses += 1
            while len(self._store) > self._maxsize:
                self._store.popitem(last=False)

        self._maybe_save_to_disk()
        return embedding.to(device)

    def get_file_hash(self, image_path: Path) -> str:
        try:
            stat = image_path.stat()
            key = str(image_path.resolve())
            with self._lock:
                cached = self._file_hash_cache.get(key)
                if cached is not None and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
                    return cached[2]
            
            h = self._sha256_key(image_path)
            with self._lock:
                self._file_hash_cache[key] = (stat.st_mtime, stat.st_size, h)
            return h
        except Exception:
            return self._sha256_key(image_path)

    def clear(self) -> None:
        """Remove all cached entries from memory and delete the on-disk file."""
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0
        if self._cache_path.exists():
            try:
                self._cache_path.unlink()
                logger.info(
                    "[EmbeddingCache] Cleared disk cache at %s", self._cache_path
                )
            except OSError as exc:
                logger.warning(
                    "[EmbeddingCache] Could not delete disk cache: %s", exc
                )

    def info(self) -> Dict[str, Any]:
        """Return a snapshot of cache statistics.

        Returns:
            Dict with keys ``size``, ``maxsize``, ``hits``, ``misses``,
            ``hit_rate``, and ``cache_path``.
        """
        with self._lock:
            size = len(self._store)
            hits = self._hits
            misses = self._misses
        total = hits + misses
        hit_rate = round(hits / total, 4) if total > 0 else 0.0
        return {
            "size": size,
            "maxsize": self._maxsize,
            "hits": hits,
            "misses": misses,
            "hit_rate": hit_rate,
            "cache_path": str(self._cache_path),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _sha256_key(image_path: Path) -> str:
        """Return the SHA-256 hex digest of ``image_path``'s raw bytes."""
        digest = hashlib.sha256()
        with image_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _compute_embedding(
        image_path: Path,
        model: Any,
        transform: Any,
        device: str,
    ) -> Any:
        """Load image, apply transform, run model, and return a CPU tensor."""
        try:
            from PIL import Image as _PILImage
        except ImportError as exc:
            raise RuntimeError(
                "[EmbeddingCache] Pillow is required for image loading. "
                "Install it with: pip install Pillow"
            ) from exc

        try:
            import torch as _torch
        except ImportError as exc:
            raise RuntimeError(
                "[EmbeddingCache] PyTorch is required for embedding computation."
            ) from exc

        img = _PILImage.open(image_path).convert("RGB")
        tensor = transform(img).unsqueeze(0).to(device)  # shape: (1, C, H, W)

        model.eval()
        with _torch.no_grad():
            embedding = model(tensor)

        # Flatten spatial dims if needed (e.g. ResNet50 outputs (1, 2048, 1, 1))
        embedding = embedding.flatten(1).squeeze(0).cpu()
        return embedding

    def _load_from_disk(self) -> None:
        """Attempt to restore the cache from the persistence file."""
        if not self._cache_path.exists():
            return
        try:
            with self._cache_path.open("rb") as fh:
                data: Dict[str, Any] = pickle.load(fh)
            if isinstance(data, dict):
                with self._lock:
                    for key, value in data.items():
                        if len(self._store) >= self._maxsize:
                            break
                        self._store[key] = value
                logger.info(
                    "[EmbeddingCache] Loaded %d entries from %s",
                    len(self._store),
                    self._cache_path,
                )
        except Exception as exc:
            logger.warning(
                "[EmbeddingCache] Failed to load disk cache (%s); starting fresh.",
                exc,
            )

    def _maybe_save_to_disk(self) -> None:
        """Persist to disk every N misses instead of on every single one."""
        with self._lock:
            self._misses_since_save += 1
            should_save = self._misses_since_save >= self._save_every_n_misses
            if should_save:
                self._misses_since_save = 0
        if should_save:
            self._save_to_disk()

    def _save_to_disk(self) -> None:
        """Persist the current cache contents to disk (best-effort)."""
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                snapshot = dict(self._store)
            import tempfile
            temp_fd, temp_path_str = tempfile.mkstemp(
                dir=str(self._cache_path.parent),
                prefix=self._cache_path.name + ".tmp",
            )
            temp_path = Path(temp_path_str)
            try:
                with os.fdopen(temp_fd, "wb") as fh:
                    pickle.dump(snapshot, fh, protocol=pickle.HIGHEST_PROTOCOL)
                    fh.flush()
                    try:
                        os.fsync(fh.fileno())
                    except OSError:
                        pass
                os.replace(temp_path, self._cache_path)
            except Exception as e:
                if temp_path.exists():
                    temp_path.unlink()
                raise e
            logger.debug(
                "[EmbeddingCache] Saved %d entries to %s",
                len(snapshot),
                self._cache_path,
            )
        except Exception as exc:
            logger.warning("[EmbeddingCache] Could not save disk cache: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton — import and use directly:
#   from visual_regression.embedding_cache import embedding_cache
# ---------------------------------------------------------------------------
embedding_cache: EmbeddingCache = EmbeddingCache()

# Disk writes are now batched (every N misses) rather than per-miss, so flush
# whatever's pending on process exit to avoid losing the most recent entries.
atexit.register(embedding_cache._save_to_disk)
