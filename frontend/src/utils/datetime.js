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
