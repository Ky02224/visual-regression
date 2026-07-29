/**
 * Custom hook for fetching and caching API data
 */

import React from 'react';
import { api, ApiClientError } from '../services/apiClient';

interface CacheEntry<T> {
  data: T;
  timestamp: number;
}

interface UseApiDataOptions {
  /** Time to live in milliseconds (default: 5 minutes) */
  ttl?: number;
  /** Automatically refetch when component mounts (default: true) */
  autoFetch?: boolean;
  /** Callback when error occurs */
  onError?: (error: Error) => void;
}

interface UseApiDataResult<T> {
  data: T | null;
  loading: boolean;
  error: Error | null;
  refetch: () => Promise<void>;
}

// Global cache for API data. Bounded with simple LRU eviction so long
// dashboard sessions (many distinct run/report/build URLs visited) don't
// grow this map without limit.
const MAX_CACHE_ENTRIES = 100;
const cache = new Map<string, CacheEntry<any>>();

function cacheGet<T>(url: string): CacheEntry<T> | undefined {
  const entry = cache.get(url);
  if (entry) {
    // Move to the end so the least-recently-used entry is always first.
    cache.delete(url);
    cache.set(url, entry);
  }
  return entry;
}

function cacheSet<T>(url: string, entry: CacheEntry<T>): void {
  cache.delete(url);
  cache.set(url, entry);
  while (cache.size > MAX_CACHE_ENTRIES) {
    const oldestKey = cache.keys().next().value;
    if (oldestKey === undefined) break;
    cache.delete(oldestKey);
  }
}

export function useApiData<T = unknown>(
  url: string,
  options: UseApiDataOptions = {}
): UseApiDataResult<T> {
  const { ttl = 5 * 60 * 1000, autoFetch = true, onError } = options;

  const [data, setData] = React.useState<T | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<Error | null>(null);

  // Callers commonly pass a fresh inline options object (and thus a fresh
  // `onError` reference) on every render. Reading it through a ref keeps
  // fetchData's identity stable across those renders — otherwise the
  // mount effect below re-fires on every re-render, not just on mount,
  // causing duplicate overlapping requests before the cache is warm.
  const onErrorRef = React.useRef(onError);
  React.useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  const fetchData = React.useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      // Check cache
      const cached = cacheGet<T>(url);
      if (cached && Date.now() - cached.timestamp < ttl) {
        setData(cached.data);
        setLoading(false);
        return;
      }

      // Fetch from API
      const result = await api.get<T>(url);
      cacheSet<T>(url, {
        data: result,
        timestamp: Date.now(),
      });
      setData(result);
    } catch (err) {
      const error = err instanceof Error ? err : new Error('Unknown error');
      setError(error);
      if (onErrorRef.current) {
        onErrorRef.current(error);
      }
    } finally {
      setLoading(false);
    }
  }, [url, ttl]);

  React.useEffect(() => {
    if (autoFetch) {
      fetchData();
    }
  }, [fetchData, autoFetch]);

  return { data, loading, error, refetch: fetchData };
}

/**
 * Clear all cached data (useful for logout or refresh)
 */
export function clearApiCache(): void {
  cache.clear();
}

/**
 * Clear specific cache entry
 */
export function clearApiCacheEntry(url: string): void {
  cache.delete(url);
}
