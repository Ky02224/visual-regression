import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useVirtualScroll } from './useVirtualScroll';

// startIndex used to only be clamped at the lower bound (>= 0), not the
// upper bound. scrollTop is state that persists across renders and is only
// updated by the onScroll handler — so if a caller stays scrolled far down
// a long list and then swaps in a much shorter `items` array (e.g.
// switching suites without unmounting), the stale scrollTop could compute a
// startIndex past the end of the new array. items.slice(startIndex,
// endIndex + 1) then returns [] and the table renders as blank.
describe('useVirtualScroll', () => {
  it('still returns visible items after items shrinks while scrolled far down', () => {
    const longList = Array.from({ length: 200 }, (_, i) => `item-${i}`);
    const { result, rerender } = renderHook(
      ({ items }) => useVirtualScroll(items, { itemHeight: 40, containerHeight: 400 }),
      { initialProps: { items: longList } }
    );

    // Simulate scrolling near the bottom of the long list.
    act(() => {
      result.current.onScroll({ currentTarget: { scrollTop: 7000 } } as any);
    });

    const shortList = Array.from({ length: 5 }, (_, i) => `short-${i}`);
    rerender({ items: shortList });

    // The stale scrollTop (7000) still anchors the view near the tail of
    // the now-much-shorter list, but the range must stay valid and
    // non-empty — this used to compute an out-of-bounds startIndex and
    // render nothing at all.
    expect(result.current.startIndex).toBeLessThanOrEqual(result.current.endIndex);
    expect(result.current.startIndex).toBeLessThan(shortList.length);
    expect(result.current.visibleItems.length).toBeGreaterThan(0);
  });

  it('clamps to an empty range without throwing when items is empty', () => {
    const { result } = renderHook(() =>
      useVirtualScroll([] as string[], { itemHeight: 40, containerHeight: 400 })
    );

    expect(result.current.visibleItems).toEqual([]);
  });
});
