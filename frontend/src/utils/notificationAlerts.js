import { toast } from 'sonner';

const RECENT_MS = 2 * 60 * 1000;
const toastedIds = new Set();

let audioContext = null;
let audioUnlocked = false;

export function unlockNotificationAudio() {
  if (audioUnlocked) return;
  try {
    const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextCtor) return;
    if (!audioContext) {
      audioContext = new AudioContextCtor();
    }
    if (audioContext.state === 'suspended') {
      audioContext.resume().catch(() => {});
    }
    audioUnlocked = true;
  } catch {
    /* non-blocking */
  }
}

export function playNotificationBeep() {
  try {
    unlockNotificationAudio();
    const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextCtor) return;

    const ctx = audioContext || new AudioContextCtor();
    audioContext = ctx;

    if (ctx.state === 'suspended') {
      ctx.resume().catch(() => {});
    }

    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = 'sine';
    o.frequency.value = 880;
    g.gain.value = 0.06;
    o.connect(g);
    g.connect(ctx.destination);
    o.start();
    setTimeout(() => {
      o.stop();
    }, 140);
  } catch {
    /* non-blocking */
  }
}

function parseCreatedMs(notification) {
  const raw = notification?.created_at_dt || notification?.created_at;
  if (!raw) return 0;
  const ms = new Date(raw).getTime();
  return Number.isFinite(ms) ? ms : 0;
}

function isAutoNotification(notification) {
  if (!notification?.id) return false;
  if (notification.is_auto) return true;
  return String(notification.id).startsWith('auto-');
}

function isStoredNotification(notification) {
  if (!notification?.id) return false;
  if (isAutoNotification(notification)) return false;
  return true;
}

function isRecentNotification(notification) {
  const created = parseCreatedMs(notification);
  if (!created) return false;
  return Date.now() - created <= RECENT_MS;
}

function shouldAlert(notification, { source = 'sse', isNewOnPoll = false } = {}) {
  if (!notification?.id) return false;
  if (toastedIds.has(notification.id)) return false;

  if (isAutoNotification(notification)) {
    return source === 'poll' && isNewOnPoll;
  }

  if (source === 'sse') return true;
  return isRecentNotification(notification);
}

function markAlerted(notification) {
  if (notification?.id) {
    toastedIds.add(notification.id);
  }
}

export function showNotificationToast(notification, { onView } = {}) {
  const title = notification?.title || 'New notification';
  const description = notification?.message || '';
  const leadId = notification?.lead_id;
  const urgency = (notification?.urgency || '').toLowerCase();
  const severity = (notification?.severity || '').toLowerCase();
  const isUrgent = urgency === 'critical' || urgency === 'urgent' || severity === 'high';

  const action = leadId
    ? {
        label: 'View',
        onClick: () => onView?.(leadId),
      }
    : undefined;

  const opts = {
    description,
    duration: 5000,
    action,
  };

  if (isUrgent) {
    toast.warning(title, opts);
  } else {
    toast.info(title, opts);
  }
}

export function alertNotification(notification, { onView, source = 'sse', isNewOnPoll = false } = {}) {
  if (!shouldAlert(notification, { source, isNewOnPoll })) return false;
  showNotificationToast(notification, { onView });
  playNotificationBeep();
  markAlerted(notification);
  return true;
}

/**
 * Process poll results: seed on initial load, alert only net-new notifications.
 * @returns {{ nextIds: Set<string>, alerted: number }}
 */
export function alertNewNotificationsFromPoll(
  prevIds,
  incoming,
  { onView, isInitialLoad = false } = {}
) {
  const nextIds = new Set(prevIds);
  let alerted = 0;

  for (const n of incoming || []) {
    if (!n?.id) continue;
    const isNew = !prevIds.has(n.id);
    nextIds.add(n.id);

    if (isInitialLoad || !isNew) continue;
    if (alertNotification(n, { onView, source: 'poll', isNewOnPoll: isNew })) {
      alerted += 1;
    }
  }

  return { nextIds, alerted };
}

export function resetNotificationAlertState() {
  toastedIds.clear();
}

/** @internal test helpers */
export const _test = {
  shouldAlert,
  isStoredNotification,
  isAutoNotification,
  isRecentNotification,
  toastedIds,
  RECENT_MS,
};
