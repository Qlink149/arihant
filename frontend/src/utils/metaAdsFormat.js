// Formatting helpers for the Meta Ads dashboard. Ratios arrive from the API
// already computed (null when undefined) - never recompute or average them here.

const DASH = '—';

export const isNum = (n) => typeof n === 'number' && Number.isFinite(n);

// Indian short form: 1.2K, 3.4L, 1.1Cr. `rupee` prefixes the ₹ sign.
export function formatCompact(n, { rupee = false } = {}) {
  if (!isNum(n)) return DASH;
  const sign = n < 0 ? '-' : '';
  const v = Math.abs(n);
  const p = rupee ? '₹' : '';
  if (v >= 1e7) return `${sign}${p}${(v / 1e7).toFixed(2)}Cr`;
  if (v >= 1e5) return `${sign}${p}${(v / 1e5).toFixed(2)}L`;
  if (v >= 1e3) return `${sign}${p}${(v / 1e3).toFixed(1)}K`;
  return `${sign}${p}${Math.round(v).toLocaleString('en-IN')}`;
}

// Full precision for tables: ₹1,23,456
export function formatINR(n) {
  if (!isNum(n)) return DASH;
  return `₹${Math.round(n).toLocaleString('en-IN')}`;
}

export function formatInt(n) {
  if (!isNum(n)) return DASH;
  return Math.round(n).toLocaleString('en-IN');
}

export function formatPct(n, digits = 2) {
  if (!isNum(n)) return DASH;
  return `${n.toFixed(digits)}%`;
}

export function formatDelta(d) {
  if (!isNum(d)) return DASH;
  return `${d > 0 ? '+' : ''}${d.toFixed(1)}%`;
}

// Metrics where a rise is bad (cost) vs good (volume). Spend is neutral:
// spending more is neither good nor bad on its own.
const COST_METRICS = new Set(['cpl', 'cpm', 'cpc']);
const NEUTRAL_METRICS = new Set(['spend']);

export function deltaTone(metric, delta) {
  if (!isNum(delta) || delta === 0 || NEUTRAL_METRICS.has(metric)) return 'neutral';
  const up = delta > 0;
  return COST_METRICS.has(metric) ? (up ? 'bad' : 'good') : (up ? 'good' : 'bad');
}

export const TONE_CLASS = {
  good: 'text-emerald-400',
  bad: 'text-red-400',
  neutral: 'text-crm-fg-muted',
};

const STATUS_LABEL = { active: 'Active', paused: 'Paused', unknown: '—' };

export function statusGroup(effectiveStatus) {
  const s = (effectiveStatus || '').toUpperCase();
  if (!s) return 'unknown';
  return s === 'ACTIVE' ? 'active' : 'paused';
}

export function statusLabel(effectiveStatus) {
  return STATUS_LABEL[statusGroup(effectiveStatus)];
}

// CSV ------------------------------------------------------------------
// Cells that start with = + - @ are formula-injection vectors in Excel when a
// campaign name is attacker-influenced, so text cells get a leading apostrophe.
export function csvCell(value) {
  if (value === null || value === undefined) return '';
  let s = String(value);
  if (typeof value === 'string' && /^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(rows, columns) {
  const header = columns.map((c) => csvCell(c.label)).join(',');
  const body = rows.map((r) => columns.map((c) => csvCell(c.value(r))).join(','));
  return [header, ...body].join('\r\n');
}

export function downloadCsv(filename, csvText) {
  const blob = new Blob(['﻿', csvText], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
