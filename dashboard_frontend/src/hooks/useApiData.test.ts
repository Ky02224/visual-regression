import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../services/apiClient';
import { clearApiCache, useApiData } from './useApiData';

describe('useApiData', () => {
  beforeEach(() => {
    clearApiCache();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    clearApiCache();
  });

  it('fetches data on mount and exposes it once loaded', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ hello: 'world' });

    const { result } = renderHook(() => useApiData<{ hello: string }>('/api/thing'));

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.data).toEqual({ hello: 'world' });
    expect(result.current.error).toBeNull();
    expect(api.get).toHaveBeenCalledTimes(1);
  });

  it('serves a second call to the same URL from cache instead of refetching', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({ hello: 'world' });

    const first = renderHook(() => useApiData('/api/cached-thing'));
    await waitFor(() => expect(first.result.current.loading).toBe(false));

    const second = renderHook(() => useApiData('/api/cached-thing'));
    await waitFor(() => expect(second.result.current.loading).toBe(false));

    expect(getSpy).toHaveBeenCalledTimes(1);
    expect(second.result.current.data).toEqual({ hello: 'world' });
  });

  it('refetches once the TTL has elapsed', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({ n: 1 });

    const { result } = renderHook(() => useApiData('/api/ttl-thing', { ttl: 10 }));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(getSpy).toHaveBeenCalledTimes(1);

    await new Promise((resolve) => setTimeout(resolve, 20));
    await act(async () => {
      await result.current.refetch();
    });

    expect(getSpy).toHaveBeenCalledTimes(2);
  });

  it('surfaces a fetch failure as an error instead of throwing', async () => {
    vi.spyOn(api, 'get').mockRejectedValue(new Error('network down'));
    const onError = vi.fn();

    const { result } = renderHook(() => useApiData('/api/broken-thing', { onError }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.data).toBeNull();
    expect(result.current.error?.message).toBe('network down');
    expect(onError).toHaveBeenCalledTimes(1);
  });

  it('does not fetch automatically when autoFetch is false', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({ n: 1 });

    const { result } = renderHook(() => useApiData('/api/manual-thing', { autoFetch: false }));
    // Give any accidental async fetch a chance to fire.
    await new Promise((resolve) => setTimeout(resolve, 10));

    expect(getSpy).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(true);
  });
});
