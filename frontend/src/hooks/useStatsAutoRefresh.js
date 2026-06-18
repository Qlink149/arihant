import { useEffect, useRef } from 'react';

const DEFAULT_INTERVAL_MS = 60_000;

/**
 * Poll stats on an interval and when the tab regains focus.
 * @param {() => void | Promise<void>} onRefresh
 * @param {{ intervalMs?: number, enabled?: boolean }} [options]
 */
export function useStatsAutoRefresh(onRefresh, options = {}) {
  const { intervalMs = DEFAULT_INTERVAL_MS, enabled = true } = options;
  const onRefreshRef = useRef(onRefresh);
  onRefreshRef.current = onRefresh;

  useEffect(() => {
    if (!enabled) return undefined;

    const run = () => {
      try {
        onRefreshRef.current?.();
      } catch {
        /* ignore refresh errors */
      }
    };

    const intervalId = window.setInterval(run, intervalMs);

    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        run();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [enabled, intervalMs]);
}

export default useStatsAutoRefresh;
