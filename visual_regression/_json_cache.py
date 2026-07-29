"""
JSON file caching layer with automatic invalidation on file modification.

This module provides a simple in-memory cache for JSON file reads, automatically
invalidating cache entries when files are modified (detected via mtime).

Usage:
    from ._json_cache import JsonCache
    
    # Read JSON with automatic caching
    data = JsonCache.read(path)  # Cached for subsequent calls
    
    # Manual cache clear if needed
    JsonCache.clear(path)
    JsonCache.clear_all()
"""

from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any, Dict


class _CacheEntry:
    """Internal cache entry with file modification tracking."""
    
    def __init__(self, data: Any, mtime: float):
        self.data = data
        self.mtime = mtime


class JsonCache:
    """Thread-safe JSON file cache with mtime-based invalidation."""
    
    _cache: Dict[Path, _CacheEntry] = {}
    _lock = threading.Lock()
    
    @classmethod
    def read(cls, path: Path | str) -> Any:
        """
        Read JSON file with caching. Automatically invalidates if file is modified.
        
        Args:
            path: Path to JSON file
            
        Returns:
            Parsed JSON data
            
        Raises:
            FileNotFoundError: If file doesn't exist
            json.JSONDecodeError: If file is invalid JSON
        """
        path = Path(path)
        
        # Check if file exists and get current mtime
        try:
            current_mtime = path.stat().st_mtime
        except FileNotFoundError:
            # Clear any stale cache entry
            with cls._lock:
                cls._cache.pop(path, None)
            raise
        
        # Return cached data if mtime matches
        with cls._lock:
            if path in cls._cache:
                entry = cls._cache[path]
                if entry.mtime == current_mtime:
                    return copy.deepcopy(entry.data)
        
        # Cache miss or stale: read and cache with transient read-conflict retries
        import time
        max_read_retries = 3
        for attempt in range(1, max_read_retries + 1):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                break
            except (json.JSONDecodeError, PermissionError):
                if attempt == max_read_retries:
                    raise
                time.sleep(0.02 * attempt)
        
        with cls._lock:
            cls._cache[path] = _CacheEntry(data, current_mtime)
        return copy.deepcopy(data)
    
    @classmethod
    def clear(cls, path: Path | str) -> None:
        """Clear cache entry for a specific file."""
        with cls._lock:
            cls._cache.pop(Path(path), None)
    
    @classmethod
    def clear_all(cls) -> None:
        """Clear entire cache."""
        with cls._lock:
            cls._cache.clear()
    
    @classmethod
    def cache_size(cls) -> int:
        """Get number of cached entries."""
        return len(cls._cache)
