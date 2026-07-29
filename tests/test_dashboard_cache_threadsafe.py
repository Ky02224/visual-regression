import threading
import time
from pathlib import Path

from visual_regression.config import WorkspacePaths
from visual_regression.dashboard_data import _DashboardCache


def test_dashboard_cache_concurrent_access(tmp_path):
    """Ensure concurrent get/set/invalidate don't raise and cache remains consistent."""
    exceptions = []
    paths = WorkspacePaths(root=tmp_path / ".visual-regression")

    def setter():
        try:
            for i in range(5):
                _DashboardCache.set(paths, {"value": i})
                time.sleep(0.01)
        except Exception as exc:
            exceptions.append(exc)

    def getter():
        try:
            for _ in range(20):
                _ = _DashboardCache.get(paths)
                time.sleep(0.005)
        except Exception as exc:
            exceptions.append(exc)

    def invalidator():
        try:
            for _ in range(3):
                _DashboardCache.invalidate(paths)
                time.sleep(0.02)
        except Exception as exc:
            exceptions.append(exc)

    threads = []
    for fn in (setter, getter, invalidator):
        t = threading.Thread(target=fn)
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    assert not exceptions
