import { useCallback } from 'react';

const DEFAULT_THRESHOLD_PX = 80;

/**
 * Returns an onScroll handler that calls onNearBottom when the scroll container
 * is within thresholdPx of its bottom edge.
 */
export function useInfiniteScrollNearBottom(scrollRef, onNearBottom, thresholdPx = DEFAULT_THRESHOLD_PX) {
  return useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - thresholdPx;
    if (nearBottom) {
      onNearBottom();
    }
  }, [scrollRef, onNearBottom, thresholdPx]);
}
