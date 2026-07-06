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

const QUARTER_END_MONTH = { 1: 3, 2: 6, 3: 9, 4: 12 };
const QUARTER_END_DAY = { 1: 31, 2: 30, 3: 30, 4: 31 };

function quarterDateBounds(year, quarter) {
  const q = Number(quarter);
  const y = Number(year);
  if (!Number.isFinite(q) || q < 1 || q > 4 || !Number.isFinite(y)) return null;
  const startMonth = (q - 1) * 3 + 1;
  const endMonth = QUARTER_END_MONTH[q];
  const endDay = QUARTER_END_DAY[q];
  const pad = (n) => String(n).padStart(2, '0');
  return {
    created_from: `${y}-${pad(startMonth)}-01`,
    created_to: `${y}-${pad(endMonth)}-${pad(endDay)}`,
  };
}

/** Map sales dashboard period to Virtual Customer created-date query params. */
export function salesPeriodToLeadDateParams({ quarter = 'all', datePeriod = {} } = {}) {
  const qRaw = (quarter || '').trim();
  if (qRaw && qRaw.toLowerCase() !== 'all') {
    let year;
    let qNum;
    if (qRaw === 'current') {
      const parts = getIstCalendarParts();
      year = parts.year;
      qNum = parts.quarter;
    } else {
      const m = qRaw.match(/^(\d{4})-Q([1-4])$/i);
      if (m) {
        year = parseInt(m[1], 10);
        qNum = parseInt(m[2], 10);
      }
    }
    const bounds = quarterDateBounds(year, qNum);
    if (bounds) return bounds;
  }

  const dash = buildSalesDashboardParams({ quarter, datePeriod });
  if (dash.days) return { days: String(dash.days) };
  const out = {};
  if (dash.created_from) out.created_from = dash.created_from;
  if (dash.created_to) out.created_to = dash.created_to;
  return out;
}
