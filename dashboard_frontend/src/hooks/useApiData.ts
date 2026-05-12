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

// Global cache for API data
const cache = new Map<string, CacheEntry<any>>();

export function useApiData<T = unknown>(
  url: string,
  options: UseApiDataOptions = {}
): UseApiDataResult<T> {
  const { ttl = 5 * 60 * 1000, autoFetch = true, onError } = options;

  const [data, setData] = React.useState<T | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<Error | null>(null);

  const fetchData = React.useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      // Check cache
      const cached = cache.get(url);
      if (cached && Date.now() - cached.timestamp < ttl) {
        setData(cached.data);
        setLoading(false);
        return;
      }

      // Fetch from API
      const result = await api.get<T>(url);
      cache.set(url, {
        data: result,
        timestamp: Date.now(),
      });
      setData(result);
    } catch (err) {
      const error = err instanceof Error ? err : new Error('Unknown error');
      setError(error);
      if (onError) {
        onError(error);
      }
    } finally {
      setLoading(false);
    }
  }, [url, ttl, onError]);

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
