import { addIstDays, formatIstYmd, getIstCalendarParts, istYmdToDate } from './datetime';

const QUARTER_LABELS = ['Jan–Mar', 'Apr–Jun', 'Jul–Sep', 'Oct–Dec'];

export function formatLocalDate(date) {
  if (typeof date === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return date;
  }
  return formatIstYmd(date instanceof Date ? date : new Date(date));
}

export function addDays(date, delta) {
  const ymd = formatLocalDate(date);
  return istYmdToDate(addIstDays(delta, istYmdToDate(ymd) || new Date()));
}

export function parseYmd(value) {
  return istYmdToDate(value);
}

export function buildQuarterOptions() {
  const options = [
    { value: 'current', label: 'Current Quarter' },
    { value: 'all', label: 'All Time' },
  ];
  const { year, quarter } = getIstCalendarParts();
  let y = year;
  let q = quarter;
  for (let i = 0; i < 8; i += 1) {
    options.push({
      value: `${y}-Q${q}`,
      label: `Q${q} ${y} · ${QUARTER_LABELS[q - 1]}`,
    });
    q -= 1;
    if (q === 0) {
      q = 4;
      y -= 1;
    }
  }
  return options;
}

export const QUARTER_OPTIONS = buildQuarterOptions();

/** @typedef {{ days?: string|number, created_from?: string, created_to?: string }} DatePeriod */

/**
 * @param {{ quarter?: string, datePeriod?: DatePeriod }} state
 */
export function buildSalesDashboardParams({ quarter = 'all', datePeriod = {} } = {}) {
  const params = {};
  if (quarter && quarter !== 'all') {
    params.quarter = quarter;
    return params;
  }
  const days = datePeriod.days != null && datePeriod.days !== ''
    ? parseInt(String(datePeriod.days), 10)
    : null;
  if (Number.isFinite(days) && days > 0) {
    params.days = days;
    return params;
  }
  if (datePeriod.created_from) params.created_from = datePeriod.created_from;
  if (datePeriod.created_to) params.created_to = datePeriod.created_to;
  return params;
}

/**
 * @param {{ quarter?: string, datePeriod?: DatePeriod }} state
 */
export function getSalesPeriodLabel({ quarter = 'all', datePeriod = {} } = {}) {
  if (quarter && quarter !== 'all') {
    return QUARTER_OPTIONS.find((o) => o.value === quarter)?.label || quarter;
  }
  if (datePeriod.days) {
    const n = parseInt(String(datePeriod.days), 10);
    if (Number.isFinite(n) && n > 0) return `Last ${n} days`;
  }
  if (datePeriod.created_from || datePeriod.created_to) {
    const from = datePeriod.created_from || '…';
    const to = datePeriod.created_to || '…';
    if (from === to) return from;
    return `${from} – ${to}`;
  }
  return 'All Time';
}

export function isDatePeriodActive(datePeriod = {}) {
  return Boolean(
    (datePeriod.days != null && datePeriod.days !== '')
    || datePeriod.created_from
    || datePeriod.created_to
  );
}

export function emptyDatePeriod() {
  return { days: '', created_from: '', created_to: '' };
}
