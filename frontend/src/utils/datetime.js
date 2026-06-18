/** Parse and format API timestamps for IST display (backend stores UTC). */

const IST = 'Asia/Kolkata';

const HAS_TZ = /(?:Z|[+-]\d{2}:?\d{2})$/i;
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
const NAIVE_DATETIME = /^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/;

/**
 * Normalize API date strings for parsing. Naive datetimes are treated as UTC.
 * @param {unknown} value
 * @returns {Date|null}
 */
export function parseApiDate(value) {
  if (value == null || value === '') return null;
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }

  let s = String(value).trim();
  if (!s) return null;

  if (DATE_ONLY.test(s)) {
    const d = new Date(`${s}T00:00:00+05:30`);
    return Number.isNaN(d.getTime()) ? null : d;
  }

  if (NAIVE_DATETIME.test(s) && !HAS_TZ.test(s)) {
    s = s.replace(' ', 'T');
    if (!s.endsWith('Z') && !/[+-]\d{2}:?\d{2}$/.test(s)) {
      const withSeconds = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(s) ? `${s}:00` : s;
      s = `${withSeconds}Z`;
    }
  }

  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

const DEFAULT_DATETIME_OPTS = {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
};

/**
 * @param {unknown} value
 * @param {Intl.DateTimeFormatOptions} [options]
 * @returns {string|null}
 */
export function formatDateTimeIST(value, options = {}) {
  const d = parseApiDate(value);
  if (!d) return null;
  return d.toLocaleString('en-IN', {
    timeZone: IST,
    ...DEFAULT_DATETIME_OPTS,
    ...options,
  });
}

/**
 * @param {unknown} value
 * @returns {string|null}
 */
export function formatDateIST(value) {
  const d = parseApiDate(value);
  if (!d) return null;
  return d.toLocaleDateString('en-IN', {
    timeZone: IST,
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  });
}

/**
 * @param {unknown} value
 * @returns {string|null}
 */
export function formatTimeIST(value) {
  const d = parseApiDate(value);
  if (!d) return null;
  return d.toLocaleTimeString('en-IN', {
    timeZone: IST,
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Format task follow-up due date/time (calendar fields in IST, not UTC instants).
 * @param {string} dateStr YYYY-MM-DD
 * @param {string} [timeStr] HH:mm or HH:mm:ss
 * @returns {string|null}
 */
export function formatDueDateTime(dateStr, timeStr) {
  if (!dateStr) return null;
  const date = String(dateStr).trim();
  if (!timeStr || !String(timeStr).trim()) {
    const d = parseApiDate(date);
    if (!d) return date;
    return d.toLocaleDateString('en-IN', {
      timeZone: IST,
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    });
  }
  const time = String(timeStr).trim();
  const normalizedTime = time.length === 5 ? `${time}:00` : time;
  const d = new Date(`${date}T${normalizedTime}+05:30`);
  if (Number.isNaN(d.getTime())) {
    return `${date} ${time}`;
  }
  return formatDateTimeIST(d);
}

/**
 * Build HH:mm (24-hour) from hour, minute, and optional AM/PM period.
 * @param {string|number} hour
 * @param {string|number} minute
 * @param {'AM'|'PM'|null|undefined} [period]
 * @returns {string}
 */
export function parseTimeTo24h(hour, minute, period) {
  let h = parseInt(String(hour), 10);
  const m = parseInt(String(minute), 10);
  if (Number.isNaN(h) || Number.isNaN(m)) return '';
  if (period) {
    if (period === 'PM' && h !== 12) h += 12;
    if (period === 'AM' && h === 12) h = 0;
  }
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

/**
 * Split HH:mm into role-appropriate picker parts.
 * @param {string} hhmm
 * @param {boolean} isAdmin
 * @returns {{ hour: string, minute: string, period?: 'AM'|'PM' }}
 */
export function splitTimeForRole(hhmm, isAdmin) {
  if (!hhmm || !/^\d{1,2}:\d{2}/.test(hhmm)) {
    return isAdmin
      ? { hour: '9', minute: '00', period: 'AM' }
      : { hour: '09', minute: '00' };
  }
  const [hStr, mStr] = hhmm.split(':');
  let h = parseInt(hStr, 10);
  const m = parseInt(mStr, 10);
  if (isAdmin) {
    const period = h >= 12 ? 'PM' : 'AM';
    if (h === 0) h = 12;
    else if (h > 12) h -= 12;
    return { hour: String(h), minute: String(m).padStart(2, '0'), period };
  }
  return { hour: String(h).padStart(2, '0'), minute: String(m).padStart(2, '0') };
}

/**
 * Current calendar date in IST as YYYY-MM-DD (for filters aligned with backend IST windows).
 * @param {Date} [date]
 * @returns {string}
 */
export function formatIstYmd(date = new Date()) {
  return date.toLocaleDateString('en-CA', { timeZone: IST });
}

/**
 * Shift an IST calendar date by N days; returns YYYY-MM-DD in IST.
 * @param {number} delta
 * @param {Date} [fromDate]
 * @returns {string}
 */
export function addIstDays(delta, fromDate = new Date()) {
  const ymd = formatIstYmd(fromDate);
  const anchor = new Date(`${ymd}T12:00:00+05:30`);
  anchor.setDate(anchor.getDate() + delta);
  return formatIstYmd(anchor);
}

/**
 * Parse YYYY-MM-DD as noon IST (stable for calendar UI components).
 * @param {string} ymd
 * @returns {Date|null}
 */
export function istYmdToDate(ymd) {
  if (!ymd || !DATE_ONLY.test(String(ymd).trim())) return null;
  const d = new Date(`${String(ymd).trim()}T12:00:00+05:30`);
  return Number.isNaN(d.getTime()) ? null : d;
}

/**
 * IST calendar parts for quarter options and similar.
 * @param {Date} [date]
 */
export function getIstCalendarParts(date = new Date()) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: IST,
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
  }).formatToParts(date);
  const pick = (type) => Number(parts.find((p) => p.type === type)?.value || 0);
  const year = pick('year');
  const month = pick('month');
  const day = pick('day');
  return { year, month, day, quarter: Math.floor((month - 1) / 3) + 1 };
}
