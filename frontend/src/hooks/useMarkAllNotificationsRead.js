import { useCallback, useRef, useState } from 'react';
import { toast } from 'sonner';
import { notificationsAPI } from '../services/api';

function optimisticClear() {
  return [];
}

/**
 * Shared UX for "Mark all read" across dropdown + page.
 *
 * - optimistic UI update (instant)
 * - disable while running
 * - dismiss auto notifications immediately (avoid flicker)
 * - toast success/error
 * - refetch once; rollback on failure
 */
export function useMarkAllNotificationsRead({ getItems, setItems, refetch }) {
  const [busy, setBusy] = useState(false);
  const snapshotRef = useRef(null);

  const markAllRead = useCallback(async () => {
    if (busy) return;
    setBusy(true);

    const snapshot = Array.isArray(getItems?.()) ? getItems() : [];
    snapshotRef.current = snapshot;
    setItems(optimisticClear());

    try {
      await notificationsAPI.markAllRead();
      toast.success('All notifications cleared');
      await refetch?.();
    } catch (err) {
      // Rollback: restore what the user saw before clicking.
      setItems(() => snapshotRef.current || snapshot);
      toast.error('Could not mark all as read. Please try again.');
    } finally {
      setBusy(false);
    }
  }, [busy, getItems, refetch, setItems]);

  return { markAllRead, busy };
}

