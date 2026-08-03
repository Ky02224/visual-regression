import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useDebounce } from './useDebounce';

// This sits behind the runs-list search box. If the timer is not cleared on
// each change, every keystroke leaves its own pending update and the list
// re-renders once per character after the delay — which looks like lag rather
// than like a bug, so it would not get reported.

describe('useDebounce', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('returns the initial value immediately', () => {
    expect(renderHook(() => useDebounce('first')).result.current).toBe('first');
  });

  it('does not update before the delay elapses', () => {
    const { result, rerender } = renderHook(({ v }) => useDebounce(v, 150), {
      initialProps: { v: 'a' },
    });

    rerender({ v: 'b' });
    act(() => { vi.advanceTimersByTime(149); });

    expect(result.current).toBe('a');
  });

  it('updates once the delay elapses', () => {
    const { result, rerender } = renderHook(({ v }) => useDebounce(v, 150), {
      initialProps: { v: 'a' },
    });

    rerender({ v: 'b' });
    act(() => { vi.advanceTimersByTime(150); });

    expect(result.current).toBe('b');
  });

  it('only emits the final value of a rapid burst', () => {
    // Typing "abc" should search once for "abc", not three times.
    const { result, rerender } = renderHook(({ v }) => useDebounce(v, 150), {
      initialProps: { v: '' },
    });

    rerender({ v: 'a' });
    act(() => { vi.advanceTimersByTime(50); });
    rerender({ v: 'ab' });
    act(() => { vi.advanceTimersByTime(50); });
    rerender({ v: 'abc' });
    act(() => { vi.advanceTimersByTime(50); });

    expect(result.current).toBe('');

    act(() => { vi.advanceTimersByTime(150); });
    expect(result.current).toBe('abc');
  });

  it('restarts the timer on each change rather than queueing updates', () => {
    const { result, rerender } = renderHook(({ v }) => useDebounce(v, 100), {
      initialProps: { v: 'a' },
    });

    rerender({ v: 'b' });
    act(() => { vi.advanceTimersByTime(90); });
    rerender({ v: 'c' });
    act(() => { vi.advanceTimersByTime(90); });

    // 180ms have passed but the last change was only 90ms ago.
    expect(result.current).toBe('a');

    act(() => { vi.advanceTimersByTime(10); });
    expect(result.current).toBe('c');
  });

  it('honours a custom delay', () => {
    const { result, rerender } = renderHook(({ v }) => useDebounce(v, 500), {
      initialProps: { v: 'a' },
    });

    rerender({ v: 'b' });
    act(() => { vi.advanceTimersByTime(200); });
    expect(result.current).toBe('a');

    act(() => { vi.advanceTimersByTime(300); });
    expect(result.current).toBe('b');
  });

  it('debounces non-string values too', () => {
    const { result, rerender } = renderHook(({ v }) => useDebounce(v, 100), {
      initialProps: { v: { page: 1 } },
    });

    const next = { page: 2 };
    rerender({ v: next });
    act(() => { vi.advanceTimersByTime(100); });

    expect(result.current).toBe(next);
  });

  it('clears its timer on unmount', () => {
    // A pending timer firing after unmount would set state on a dead component.
    const clearSpy = vi.spyOn(globalThis, 'clearTimeout');
    const { unmount, rerender } = renderHook(({ v }) => useDebounce(v, 100), {
      initialProps: { v: 'a' },
    });

    rerender({ v: 'b' });
    unmount();

    expect(clearSpy).toHaveBeenCalled();
    clearSpy.mockRestore();
  });
});
