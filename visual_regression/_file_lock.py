"""
Cross-platform file locking utilities for safe concurrent access to shared resources.

This module provides simple file-based locking mechanisms to prevent race conditions
when multiple processes access the same files simultaneously.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Generator


class FileLock:
    """
    Cross-platform file lock using a lock file.
    
    Uses a lock file as a mechanism to coordinate access between processes.
    On acquisition, creates a lock file. On release, removes it.
    """
    
    def __init__(self, lock_path: Path, timeout: float = 10.0, poll_interval: float = 0.1):
        """
        Initialize file lock.
        
        Args:
            lock_path: Path where lock file will be created
            timeout: Max seconds to wait for lock acquisition (default 10s)
            poll_interval: Time between lock check attempts (default 0.1s)
        """
        self.lock_path = Path(lock_path)
        self.timeout = timeout
        self.poll_interval = poll_interval
    
    def acquire(self) -> None:
        """
        Acquire the lock, blocking until available or timeout.
        
        Raises:
            TimeoutError: If lock not acquired within timeout
        """
        start_time = time.time()
        while True:
            try:
                # Try to create lock file exclusively (atomic on most filesystems)
                # Use os.open with O_CREAT | O_EXCL for atomic create
                import os
                fd = os.open(
                    str(self.lock_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY
                )
                os.close(fd)
                return  # Success
            except FileExistsError:
                # Lock file exists, someone else has the lock
                if time.time() - start_time > self.timeout:
                    raise TimeoutError(f"Could not acquire lock {self.lock_path} within {self.timeout}s")
                time.sleep(self.poll_interval)
    
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
    import os
    os.replace(str(src), str(dst))
