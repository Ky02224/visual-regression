import { useState, useEffect, UIEvent } from 'react';

interface UseVirtualScrollOptions {
  itemHeight: number;
  containerHeight: number;
  buffer?: number;
}

export function useVirtualScroll<T>(
  items: T[],
  options: UseVirtualScrollOptions
) {
  const { itemHeight, containerHeight, buffer = 5 } = options;
  const [scrollTop, setScrollTop] = useState(0);

  const totalHeight = items.length * itemHeight;
  
  // Calculate index range. scrollTop is only updated by the onScroll handler
  // below, so if the caller swaps in a shorter `items` array while staying
  // scrolled far down a previous (longer) list, an unclamped startIndex can
  // exceed the new items.length — items.slice(startIndex, endIndex + 1) then
  // returns [] and the table renders as blank until the next scroll event.
  const lastIndex = Math.max(0, items.length - 1);
  const startIndex = Math.min(Math.max(0, Math.floor(scrollTop / itemHeight) - buffer), lastIndex);
  const endIndex = Math.min(
    lastIndex,
    Math.floor((scrollTop + containerHeight) / itemHeight) + buffer
  );

  const visibleItems = items.slice(startIndex, endIndex + 1).map((item, index) => ({
    item,
    index: startIndex + index,
    style: {
      position: 'absolute' as const,
      top: 0,
      left: 0,
      width: '100%',
      height: itemHeight,
      transform: `translateY(${(startIndex + index) * itemHeight}px)`,
    },
  }));

  const onScroll = (e: UIEvent<HTMLElement>) => {
    setScrollTop(e.currentTarget.scrollTop);
  };

  return {
    visibleItems,
    totalHeight,
    onScroll,
    startIndex,
    endIndex,
  };
}
