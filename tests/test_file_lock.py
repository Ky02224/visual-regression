import os
import sys
import time
from unittest.mock import patch

import pytest

from visual_regression._file_lock import FileLock, _pid_is_alive


def test_basic_acquire_release(tmp_path):
    lock_path = tmp_path / "test.lock"
    lock = FileLock(lock_path, timeout=2.0)
    lock.acquire()
    assert lock_path.exists()
    lock.release()
    assert not lock_path.exists()


def test_context_manager(tmp_path):
    lock_path = tmp_path / "test.lock"
    with FileLock(lock_path, timeout=2.0):
        assert lock_path.exists()
    assert not lock_path.exists()


def test_live_lock_blocks_and_times_out(tmp_path):
    """A lock file owned by the current (alive) process must not be treated as stale."""
    lock_path = tmp_path / "test.lock"
    lock_path.write_text(str(os.getpid()), encoding="ascii")
    lock = FileLock(lock_path, timeout=0.3, poll_interval=0.05, stale_after=0.0)
    with pytest.raises(TimeoutError):
        lock.acquire()
    # The lock file must still be there — it was correctly recognized as live.
    assert lock_path.exists()


def test_stale_lock_from_dead_pid_is_broken(tmp_path):
    """A lock file whose owning PID is no longer running should be cleared
    automatically instead of wedging every future acquirer forever."""
    lock_path = tmp_path / "test.lock"
    # A PID essentially guaranteed not to correspond to a live process.
    dead_pid = 999999
    lock_path.write_text(str(dead_pid), encoding="ascii")
    # Backdate the file so it's older than stale_after.
    old_time = time.time() - 1000
    os.utime(lock_path, (old_time, old_time))

    lock = FileLock(lock_path, timeout=2.0, poll_interval=0.05, stale_after=5.0)
    lock.acquire()  # Should succeed quickly by breaking the stale lock, not time out.
    assert lock_path.exists()
    # New lock file should now be tagged with our own (live) PID.
    assert lock_path.read_text(encoding="ascii").strip() == str(os.getpid())
    lock.release()


def test_recent_lock_from_dead_pid_still_blocks(tmp_path):
    """Even with a dead PID, a lock file younger than stale_after must not be broken."""
    lock_path = tmp_path / "test.lock"
    lock_path.write_text("999999", encoding="ascii")
    lock = FileLock(lock_path, timeout=0.3, poll_interval=0.05, stale_after=120.0)
    with pytest.raises(TimeoutError):
        lock.acquire()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific OpenProcess liveness check")
def test_windows_access_denied_fails_safe_as_alive():
    """OpenProcess returning a NULL handle used to be treated uniformly as
    "process is dead", but Windows also returns NULL for a live process
    owned by a different user/elevation level (ERROR_ACCESS_DENIED) — that
    case must fail safe (alive), matching the POSIX PermissionError branch,
    not silently let a live lock get broken out from under its owner."""
    import ctypes

    class _FakeKernel32:
        def OpenProcess(self, *_a, **_kw):
            return 0  # NULL handle

        def CloseHandle(self, *_a, **_kw):
            return True

    with patch("ctypes.WinDLL", return_value=_FakeKernel32()), \
         patch("ctypes.get_last_error", return_value=5):  # ERROR_ACCESS_DENIED
        assert _pid_is_alive(4) is True  # PID 4 is the Windows System process

    with patch("ctypes.WinDLL", return_value=_FakeKernel32()), \
         patch("ctypes.get_last_error", return_value=87):  # ERROR_INVALID_PARAMETER
        assert _pid_is_alive(999999) is False
