"""Tests for the embedding LRU cache.

206 statements at 0% coverage. This sits on the hot path of every AI-mode
comparison — a wrong cache key returns another image's embedding, which the
model then classifies confidently and wrongly, with no error anywhere. Cheap to
get wrong, expensive to notice.

A stub backbone stands in for ResNet50: these tests are about the caching
contract (keying, LRU eviction, accounting, persistence, concurrency), not about
what the network computes.
"""

from __future__ import annotations

import pickle
import threading
import time

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from visual_regression.embedding_cache import EmbeddingCache  # noqa: E402


class _StubBackbone:
    """Returns a fixed-width embedding and counts how often it actually ran."""

    def __init__(self, width: int = 8):
        self.width = width
        self.calls = 0

    def eval(self):
        return self

    def __call__(self, tensor):
        self.calls += 1
        batch = tensor.shape[0] if hasattr(tensor, "shape") else 1
        return torch.arange(batch * self.width, dtype=torch.float32).reshape(batch, self.width)


def _rgb(value: int) -> np.ndarray:
    return np.full((16, 16, 3), value, dtype=np.uint8)


@pytest.fixture
def cache(tmp_path):
    return EmbeddingCache(maxsize=3, cache_path=tmp_path / "emb.pkl")


# ---------------------------------------------------------------------------
# Keying and hit/miss behaviour
# ---------------------------------------------------------------------------

class TestArrayCaching:
    def test_first_call_is_a_miss_and_runs_the_model(self, cache):
        model = _StubBackbone()
        cache.get_or_compute_array(_rgb(10), model)
        assert model.calls == 1
        assert cache.info()["misses"] == 1
        assert cache.info()["hits"] == 0

    def test_identical_array_hits_without_rerunning_the_model(self, cache):
        model = _StubBackbone()
        cache.get_or_compute_array(_rgb(10), model)
        cache.get_or_compute_array(_rgb(10), model)
        assert model.calls == 1
        assert cache.info()["hits"] == 1

    def test_different_arrays_do_not_collide(self, cache):
        model = _StubBackbone()
        cache.get_or_compute_array(_rgb(10), model)
        cache.get_or_compute_array(_rgb(200), model)
        assert model.calls == 2
        assert cache.info()["size"] == 2

    def test_backbone_name_is_part_of_the_key(self, cache):
        """Two architectures produce different embeddings for the same pixels;
        sharing a key would hand one model the other's vector."""
        model = _StubBackbone()
        cache.get_or_compute_array(_rgb(10), model, backbone_name="resnet50")
        cache.get_or_compute_array(_rgb(10), model, backbone_name="efficientnet_b0")
        assert model.calls == 2
        assert cache.info()["size"] == 2

    def test_a_hit_returns_the_same_values_as_the_miss(self, cache):
        model = _StubBackbone()
        first = cache.get_or_compute_array(_rgb(10), model)
        second = cache.get_or_compute_array(_rgb(10), model)
        assert torch.allclose(first.float(), second.float(), atol=1e-2)


# ---------------------------------------------------------------------------
# LRU eviction
# ---------------------------------------------------------------------------

class TestEviction:
    def test_size_never_exceeds_maxsize(self, cache):
        model = _StubBackbone()
        for value in range(10):
            cache.get_or_compute_array(_rgb(value * 20), model)
        assert cache.info()["size"] == 3

    def test_the_least_recently_used_entry_is_evicted_first(self, cache):
        model = _StubBackbone()
        cache.get_or_compute_array(_rgb(10), model)
        cache.get_or_compute_array(_rgb(50), model)
        cache.get_or_compute_array(_rgb(90), model)

        # Touch the oldest so it is no longer least-recently-used.
        cache.get_or_compute_array(_rgb(10), model)
        calls_before = model.calls

        # Overflow by one: 50 should go, 10 should survive.
        cache.get_or_compute_array(_rgb(130), model)
        cache.get_or_compute_array(_rgb(10), model)
        assert model.calls == calls_before + 1, "the recently-used entry was evicted"

        cache.get_or_compute_array(_rgb(50), model)
        assert model.calls == calls_before + 2, "the stale entry survived eviction"


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

class TestInfo:
    def test_reports_zero_hit_rate_before_any_use(self, cache):
        info = cache.info()
        assert info["hits"] == 0
        assert info["misses"] == 0
        assert info["hit_rate"] == 0.0

    def test_hit_rate_reflects_hits_over_total(self, cache):
        model = _StubBackbone()
        cache.get_or_compute_array(_rgb(10), model)   # miss
        cache.get_or_compute_array(_rgb(10), model)   # hit
        cache.get_or_compute_array(_rgb(10), model)   # hit
        assert cache.info()["hit_rate"] == pytest.approx(2 / 3, abs=1e-4)

    def test_exposes_its_configured_limits(self, cache, tmp_path):
        info = cache.info()
        assert info["maxsize"] == 3
        assert info["cache_path"] == str(tmp_path / "emb.pkl")


# ---------------------------------------------------------------------------
# File hashing
# ---------------------------------------------------------------------------

class TestFileHash:
    def test_same_content_hashes_the_same(self, cache, tmp_path):
        a, b = tmp_path / "a.bin", tmp_path / "b.bin"
        a.write_bytes(b"identical")
        b.write_bytes(b"identical")
        assert cache.get_file_hash(a) == cache.get_file_hash(b)

    def test_different_content_hashes_differently(self, cache, tmp_path):
        a, b = tmp_path / "a.bin", tmp_path / "b.bin"
        a.write_bytes(b"one")
        b.write_bytes(b"two")
        assert cache.get_file_hash(a) != cache.get_file_hash(b)

    def test_rewriting_a_file_invalidates_its_cached_hash(self, cache, tmp_path):
        """The stat-based shortcut must not keep serving a stale digest after
        the file's contents change — that would silently reuse the old
        embedding for new pixels."""
        path = tmp_path / "img.bin"
        path.write_bytes(b"before")
        first = cache.get_file_hash(path)

        time.sleep(0.01)
        path.write_bytes(b"after-and-longer")
        assert cache.get_file_hash(path) != first

    def test_missing_file_raises(self, cache, tmp_path):
        with pytest.raises(OSError):
            cache.get_file_hash(tmp_path / "absent.bin")


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_saved_entries_are_restored_by_a_new_instance(self, tmp_path):
        path = tmp_path / "emb.pkl"
        first = EmbeddingCache(maxsize=10, cache_path=path)
        model = _StubBackbone()
        first.get_or_compute_array(_rgb(10), model)
        first._save_to_disk()

        second = EmbeddingCache(maxsize=10, cache_path=path)
        assert second.info()["size"] == 1

        second.get_or_compute_array(_rgb(10), model)
        assert model.calls == 1, "restored entry was not used"

    def test_save_is_atomic_and_leaves_no_temp_files(self, tmp_path):
        path = tmp_path / "emb.pkl"
        cache = EmbeddingCache(maxsize=10, cache_path=path)
        cache.get_or_compute_array(_rgb(10), _StubBackbone())
        cache._save_to_disk()

        assert path.exists()
        assert [p.name for p in tmp_path.iterdir() if ".tmp" in p.name] == []

    def test_a_corrupt_cache_file_starts_fresh_instead_of_crashing(self, tmp_path):
        path = tmp_path / "emb.pkl"
        path.write_bytes(b"this is not a pickle")

        cache = EmbeddingCache(maxsize=10, cache_path=path)

        assert cache.info()["size"] == 0

    def test_load_respects_maxsize(self, tmp_path):
        path = tmp_path / "emb.pkl"
        path.write_bytes(pickle.dumps({f"key{i}": torch.zeros(4) for i in range(20)}))

        cache = EmbeddingCache(maxsize=5, cache_path=path)

        assert cache.info()["size"] <= 5

    def test_writes_are_batched_not_per_miss(self, tmp_path):
        """A pickle dump plus fsync on every miss serialises inference behind
        disk I/O, which is why saves are batched."""
        path = tmp_path / "emb.pkl"
        cache = EmbeddingCache(maxsize=100, cache_path=path)
        model = _StubBackbone()

        cache.get_or_compute_array(_rgb(10), model)
        assert not path.exists(), "saved on the very first miss"

        for value in range(1, cache._save_every_n_misses + 1):
            cache.get_or_compute_array(_rgb(value), model)
        assert path.exists(), "never saved despite passing the batch threshold"


class TestClear:
    def test_clear_empties_memory_and_resets_counters(self, cache):
        cache.get_or_compute_array(_rgb(10), _StubBackbone())
        cache.clear()
        info = cache.info()
        assert info["size"] == 0
        assert info["hits"] == 0
        assert info["misses"] == 0

    def test_clear_removes_the_disk_file(self, tmp_path):
        path = tmp_path / "emb.pkl"
        cache = EmbeddingCache(maxsize=10, cache_path=path)
        cache.get_or_compute_array(_rgb(10), _StubBackbone())
        cache._save_to_disk()
        assert path.exists()

        cache.clear()

        assert not path.exists()

    def test_clear_is_safe_when_nothing_was_ever_saved(self, cache):
        cache.clear()
        assert cache.info()["size"] == 0


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------

class TestConcurrency:
    def test_concurrent_requests_for_one_key_compute_it_once(self, cache):
        """The _pending set exists so parallel captures of the same image do not
        each pay for the same forward pass."""
        started = threading.Barrier(4)

        class _SlowBackbone(_StubBackbone):
            def __call__(self, tensor):
                time.sleep(0.05)
                return super().__call__(tensor)

        model = _SlowBackbone()
        array = _rgb(77)

        def worker():
            started.wait(timeout=5)
            cache.get_or_compute_array(array, model)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
            assert not t.is_alive(), "a worker blocked — likely a lock held across the compute"

        assert model.calls == 1
        assert cache.info()["size"] == 1

    def test_parallel_distinct_keys_all_land(self, cache):
        big_cache = EmbeddingCache(maxsize=50, cache_path=cache._cache_path)
        model = _StubBackbone()

        def worker(value):
            big_cache.get_or_compute_array(_rgb(value), model)

        threads = [threading.Thread(target=worker, args=(v,)) for v in range(0, 100, 10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert big_cache.info()["size"] == 10
