import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('sonner', () => ({
  toast: {
    info: vi.fn(),
    warning: vi.fn(),
  },
}));

import { toast } from 'sonner';
import {
  _test,
  alertNewNotificationsFromPoll,
  alertNotification,
  resetNotificationAlertState,
} from './notificationAlerts';

describe('notificationAlerts', () => {
  beforeEach(() => {
    resetNotificationAlertState();
    _test.toastedIds.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    resetNotificationAlertState();
    _test.toastedIds.clear();
  });

  it('does not alert on initial poll load', () => {
    const items = [
      {
        id: 'n1',
        title: 'Task',
        message: 'Due soon',
        created_at_dt: new Date().toISOString(),
      },
      {
        id: 'auto-rnr-1',
        is_auto: true,
        title: 'RNR',
        message: 'Follow up',
        created_at_dt: new Date().toISOString(),
      },
    ];
    const { nextIds, alerted } = alertNewNotificationsFromPoll(new Set(), items, {
      isInitialLoad: true,
    });
    expect(alerted).toBe(0);
    expect(nextIds.has('n1')).toBe(true);
    expect(nextIds.has('auto-rnr-1')).toBe(true);
    expect(toast.info).not.toHaveBeenCalled();
  });

  it('alerts stored SSE notification once', () => {
    const n = {
      id: 'sse-1',
      title: 'New Lead',
      message: 'Assigned to you',
      created_at_dt: new Date().toISOString(),
    };
    expect(alertNotification(n, { source: 'sse' })).toBe(true);
    expect(toast.info).toHaveBeenCalledTimes(1);
    expect(alertNotification(n, { source: 'sse' })).toBe(false);
  });

  it('alerts new auto notification on poll once', () => {
    const prev = new Set();
    const items = [
      {
        id: 'auto-rnr-2',
        is_auto: true,
        title: 'RNR Follow-up Needed',
        message: 'Follow up',
        created_at_dt: new Date().toISOString(),
      },
    ];
    const first = alertNewNotificationsFromPoll(prev, items, { isInitialLoad: false });
    expect(first.alerted).toBe(1);
    expect(toast.info).toHaveBeenCalledTimes(1);

    const second = alertNewNotificationsFromPoll(first.nextIds, items, { isInitialLoad: false });
    expect(second.alerted).toBe(0);
  });

  it('does not re-alert same auto notification on repeated poll', () => {
    const items = [
      {
        id: 'auto-dormant-1',
        is_auto: true,
        title: 'Dormant Lead',
        message: 'No activity',
        created_at_dt: new Date().toISOString(),
      },
    ];
    const seeded = alertNewNotificationsFromPoll(new Set(), items, { isInitialLoad: true });
    const { alerted } = alertNewNotificationsFromPoll(seeded.nextIds, items, { isInitialLoad: false });
    expect(alerted).toBe(0);
    expect(toast.info).not.toHaveBeenCalled();
  });

  it('alerts recent stored notification discovered on poll', () => {
    const prev = new Set();
    const items = [
      {
        id: 'new-1',
        title: 'Reminder',
        message: 'Site visit tomorrow',
        created_at_dt: new Date().toISOString(),
      },
    ];
    const { alerted } = alertNewNotificationsFromPoll(prev, items, { isInitialLoad: false });
    expect(alerted).toBe(1);
    expect(toast.info).toHaveBeenCalledTimes(1);
  });

  it('skips stale notifications on poll', () => {
    const prev = new Set();
    const old = new Date(Date.now() - 10 * 60 * 1000).toISOString();
    const items = [
      {
        id: 'old-1',
        title: 'Old',
        message: 'Not recent',
        created_at_dt: old,
      },
    ];
    const { alerted } = alertNewNotificationsFromPoll(prev, items, { isInitialLoad: false });
    expect(alerted).toBe(0);
  });

  it('uses warning toast for critical urgency', () => {
    alertNotification(
      {
        id: 'crit-1',
        title: 'RNR Stale',
        message: 'Unreachable',
        urgency: 'critical',
        created_at_dt: new Date().toISOString(),
      },
      { source: 'sse' }
    );
    expect(toast.warning).toHaveBeenCalledTimes(1);
  });
});
