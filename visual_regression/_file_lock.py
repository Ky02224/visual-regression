"""
Cross-platform file locking utilities for safe concurrent access to shared resources.

This module provides simple file-based locking mechanisms to prevent race conditions
when multiple processes access the same files simultaneously.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def _pid_is_alive(pid: int) -> bool:
    """Best-effort liveness check for a lock file's owning PID.

    Fails safe: returns True (assume alive) whenever liveness can't be
    determined, so an uncertain check never causes a live lock to be broken.
    """
    if pid <= 0:
        return False
    try:
        if sys.platform == "win32":
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            ERROR_INVALID_PARAMETER = 87
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                # OpenProcess fails both when the PID doesn't exist
                # (ERROR_INVALID_PARAMETER) and when it exists but belongs to
                # another user/elevation level (ERROR_ACCESS_DENIED) — only
                # the former means "dead"; the latter must fail safe (alive),
                # matching the POSIX PermissionError branch below.
                return ctypes.get_last_error() != ERROR_INVALID_PARAMETER
            kernel32.CloseHandle(handle)
            return True
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists but we can't signal it -> still alive
    except Exception:
        return True  # unsure -> fail safe, don't break a possibly-live lock


class FileLock:
    """
    Cross-platform file lock using a lock file.

    Uses a lock file as a mechanism to coordinate access between processes.
    On acquisition, creates a lock file. On release, removes it.
    """

    def __init__(
        self,
        lock_path: Path,
        timeout: float = 10.0,
        poll_interval: float = 0.1,
        stale_after: float = 120.0,
    ):
        """
        Initialize file lock.

        Args:
            lock_path: Path where lock file will be created
            timeout: Max seconds to wait for lock acquisition (default 10s)
            poll_interval: Time between lock check attempts (default 0.1s)
            stale_after: Seconds after which a lock file is eligible to be
                treated as abandoned (e.g. left behind by a crashed process)
                and forcibly cleared, provided its recorded owner PID is no
                longer running. Must be well above any realistic legitimate
                hold time so a live, slow holder is never mistaken for dead.
        """
        self.lock_path = Path(lock_path)
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.stale_after = stale_after

    def acquire(self) -> None:
        """
        Acquire the lock, blocking until available or timeout.

        If an existing lock file looks abandoned (older than ``stale_after``
        and its owning PID is no longer alive), it is cleared and
        acquisition is retried immediately rather than waiting out the
        timeout — otherwise a crashed process would wedge every future
        acquirer forever, since nothing else ever removes the file.

        Raises:
            TimeoutError: If lock not acquired within timeout
        """
        start_time = time.time()
        while True:
            try:
                # Try to create lock file exclusively (atomic on most filesystems)
                # Use os.open with O_CREAT | O_EXCL for atomic create
                fd = os.open(
                    str(self.lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY
                )
                try:
                    os.write(fd, str(os.getpid()).encode("ascii"))
                finally:
                    os.close(fd)
                return  # Success
            except FileExistsError:
                # Lock file exists, someone else has the lock — unless it's
                # abandoned, in which case clear it and retry right away.
                if self._break_if_stale():
                    continue
                if time.time() - start_time > self.timeout:
                    raise TimeoutError(f"Could not acquire lock {self.lock_path} within {self.timeout}s")
                time.sleep(self.poll_interval)

    def _break_if_stale(self) -> bool:
        """Remove the lock file if it's old and its owning process is dead.

        Returns True if the lock was cleared (caller should retry
        acquisition immediately) and False if it's still live or already gone.
        """
        try:
            stat = self.lock_path.stat()
        except FileNotFoundError:
            return False
        if time.time() - stat.st_mtime <= self.stale_after:
            return False
        owner_alive = True
        try:
            pid_text = self.lock_path.read_text(encoding="ascii").strip()
            owner_alive = _pid_is_alive(int(pid_text)) if pid_text else False
        except Exception:
            # Lock file predates PID-tagging or is unreadable — treat as
            # abandoned only because it's already past stale_after in age.
            owner_alive = False
        if owner_alive:
            return False
        try:
            self.lock_path.unlink()
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False

    def release(self) -> None:
        """Release the lock by removing lock file."""
        try:
            self.lock_path.unlink()
        except FileNotFoundError:
            pass  # Already released or never acquired

    def __enter__(self) -> FileLock:
        """Context manager entry."""
        self.acquire()
        return self

    def __exit__(self, *args: object) -> None:
        """Context manager exit."""
        self.release()


def atomic_replace(src: Path, dst: Path) -> None:
    """
    Atomically replace destination file with source file.

    On most filesystems, os.replace() is atomic. This is safer than
    copy + delete since there's no window where dst is missing.

    Args:
        src: Source file path
        dst: Destination file path
    """
    os.replace(str(src), str(dst))
