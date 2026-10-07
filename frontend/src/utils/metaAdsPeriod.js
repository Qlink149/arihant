// Date-range presets for the Meta Ads dashboard. All dates are IST calendar
// days (YYYY-MM-DD) because the ad account reports in Asia/Kolkata.

const IST_OFFSET_MS = 5.5 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

export function istToday(now = Date.now()) {
  return new Date(now + IST_OFFSET_MS).toISOString().slice(0, 10);
}

export function shiftDay(ymd, days) {
  const t = Date.parse(`${ymd}T00:00:00Z`) + days * DAY_MS;
  return new Date(t).toISOString().slice(0, 10);
}

function monthStart(ymd) {
  return `${ymd.slice(0, 7)}-01`;
}

export const PRESETS = [
  { key: '7d', label: '7 days' },
  { key: '14d', label: '14 days' },
  { key: '30d', label: '30 days' },
  { key: '90d', label: '90 days' },
  { key: 'this_month', label: 'This month' },
  { key: 'last_month', label: 'Last month' },
];

// Returns { from, to } for a preset key, or null for an unknown key (custom).
export function presetRange(key, now = Date.now()) {
  const today = istToday(now);
  const trailing = { '7d': 7, '14d': 14, '30d': 30, '90d': 90 }[key];
  if (trailing) return { from: shiftDay(today, -(trailing - 1)), to: today };
  if (key === 'this_month') return { from: monthStart(today), to: today };
  if (key === 'last_month') {
    const lastOfPrev = shiftDay(monthStart(today), -1);
    return { from: monthStart(lastOfPrev), to: lastOfPrev };
  }
  return null;
}

export function rangeDays(from, to) {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / DAY_MS) + 1;
}

export function isValidRange(from, to) {
  return /^\d{4}-\d{2}-\d{2}$/.test(from || '') && /^\d{4}-\d{2}-\d{2}$/.test(to || '') && from <= to && rangeDays(from, to) <= 400;
}

// Which preset (if any) the current range equals - used to highlight the chip.
export function matchPreset(from, to, now = Date.now()) {
  return PRESETS.find((p) => {
    const r = presetRange(p.key, now);
    return r && r.from === from && r.to === to;
  })?.key || null;
}
