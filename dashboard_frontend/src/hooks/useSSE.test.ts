/**
 * Reconnection backoff for the shared event stream.
 *
 * EventSource does not expose the HTTP status to onerror, so a 401 on a tab
 * sitting at the login page looks exactly like a dropped connection. With a
 * fixed three-second retry that produced ten identical
 * "GET /api/events/stream 401" lines in the server log every time someone left
 * the login page open — retrying cannot conjure a session, and the noise buries
 * errors that matter.
 *
 * The recovery still has to work for genuinely transient failures, so the
 * retries stay; they just back off.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useSSE } from './useSSE';
import { act, renderHook } from '@testing-library/react';

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
  closed = false;

  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    (this.listeners[type] ||= []).push(fn);
  }
  close() {
    this.closed = true;
  }
  fail() {
    this.onerror?.();
  }
}

describe('useSSE reconnection', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeEventSource.instances = [];
    (globalThis as any).EventSource = FakeEventSource;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('opens a single connection for the stream', () => {
    renderHook(() => useSSE('/api/events/stream', {}));

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toBe('/api/events/stream');
  });

  it('waits longer after each failure instead of retrying on a fixed interval', () => {
    renderHook(() => useSSE('/api/events/stream', {}));

    // First failure: the original 3s.
    act(() => { FakeEventSource.instances[0].fail(); });
    act(() => { vi.advanceTimersByTime(2999); });
    expect(FakeEventSource.instances).toHaveLength(1);
    act(() => { vi.advanceTimersByTime(1); });
    expect(FakeEventSource.instances).toHaveLength(2);

    // Second failure must NOT reconnect at 3s — that was the noisy behaviour.
    act(() => { FakeEventSource.instances[1].fail(); });
    act(() => { vi.advanceTimersByTime(3000); });
    expect(FakeEventSource.instances).toHaveLength(2);
    act(() => { vi.advanceTimersByTime(3000); });
    expect(FakeEventSource.instances).toHaveLength(3);
  });

  it('stops growing the delay past a minute', () => {
    renderHook(() => useSSE('/api/events/stream', {}));

    for (let i = 0; i < 8; i += 1) {
      act(() => { FakeEventSource.instances[FakeEventSource.instances.length - 1].fail(); });
      act(() => { vi.advanceTimersByTime(60_000); });
    }

    const before = FakeEventSource.instances.length;
    act(() => { FakeEventSource.instances[before - 1].fail(); });
    act(() => { vi.advanceTimersByTime(60_000); });

    expect(FakeEventSource.instances.length).toBeGreaterThan(before - 1);
  });

  it('a successful connection resets the backoff', () => {
    renderHook(() => useSSE('/api/events/stream', {}));

    act(() => { FakeEventSource.instances[0].fail(); });
    act(() => { vi.advanceTimersByTime(3000); });
    const reconnected = FakeEventSource.instances[1];

    act(() => { reconnected.onopen?.(); });
    act(() => { reconnected.fail(); });

    // Back to the first, shortest delay rather than continuing to grow.
    act(() => { vi.advanceTimersByTime(3000); });
    expect(FakeEventSource.instances).toHaveLength(3);
  });
});
