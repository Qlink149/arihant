import { describe, it, expect } from 'vitest';
import {
  formatCompact, formatINR, formatInt, formatPct, formatDelta, deltaTone,
  statusGroup, statusLabel, csvCell, toCsv,
} from './metaAdsFormat';
import { istToday, shiftDay, presetRange, rangeDays, isValidRange, matchPreset } from './metaAdsPeriod';

describe('metaAdsFormat', () => {
  it('formats compact Indian units and dashes for missing values', () => {
    expect(formatCompact(950)).toBe('950');
    expect(formatCompact(1500)).toBe('1.5K');
    expect(formatCompact(1926951, { rupee: true })).toBe('₹19.27L');
    expect(formatCompact(25000000)).toBe('2.50Cr');
    expect(formatCompact(null)).toBe('—');
    expect(formatCompact(undefined)).toBe('—');
    expect(formatCompact(NaN)).toBe('—');
  });

  it('keeps zero as a real value, not a dash', () => {
    expect(formatINR(0)).toBe('₹0');
    expect(formatInt(0)).toBe('0');
    expect(formatPct(0)).toBe('0.00%');
  });

  it('formats full INR, ints, pct and deltas', () => {
    expect(formatINR(123456)).toBe('₹1,23,456');
    expect(formatINR(null)).toBe('—');
    expect(formatPct(1.234)).toBe('1.23%');
    expect(formatPct(null)).toBe('—');
    expect(formatDelta(12.34)).toBe('+12.3%');
    expect(formatDelta(-5)).toBe('-5.0%');
    expect(formatDelta(null)).toBe('—');
  });

  it('colours deltas by whether a rise is good: cost up = bad, volume up = good, spend neutral', () => {
    expect(deltaTone('cpl', 10)).toBe('bad');
    expect(deltaTone('cpl', -10)).toBe('good');
    expect(deltaTone('leads', 10)).toBe('good');
    expect(deltaTone('leads', -10)).toBe('bad');
    expect(deltaTone('spend', 50)).toBe('neutral');
    expect(deltaTone('leads', 0)).toBe('neutral');
    expect(deltaTone('leads', null)).toBe('neutral');
  });

  it('buckets Meta statuses into active / paused / unknown', () => {
    expect(statusGroup('ACTIVE')).toBe('active');
    expect(statusGroup('CAMPAIGN_PAUSED')).toBe('paused');
    expect(statusGroup('ARCHIVED')).toBe('paused');
    expect(statusGroup(null)).toBe('unknown');
    expect(statusLabel('active')).toBe('Active');
    expect(statusLabel(undefined)).toBe('—');
  });

  it('escapes CSV cells and neutralises spreadsheet formulas', () => {
    expect(csvCell('plain')).toBe('plain');
    expect(csvCell('a,b')).toBe('"a,b"');
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
    expect(csvCell('=HYPERLINK("x")')).toBe('"\'=HYPERLINK(""x"")"');
    expect(csvCell('+1')).toBe("'+1");
    expect(csvCell(-5)).toBe('-5'); // real numbers stay numbers
    expect(csvCell(null)).toBe('');
    expect(csvCell(0)).toBe('0');
  });

  it('builds CSV with header and CRLF rows', () => {
    const csv = toCsv(
      [{ n: 'A', s: 10 }, { n: 'B,C', s: null }],
      [{ label: 'Name', value: (r) => r.n }, { label: 'Spend', value: (r) => r.s }],
    );
    expect(csv).toBe('Name,Spend\r\nA,10\r\n"B,C",');
  });
});

describe('metaAdsPeriod', () => {
  // 2026-10-07 20:00 UTC is already 2026-10-08 01:30 in IST
  const NOW = Date.UTC(2026, 9, 7, 20, 0, 0);

  it('uses the IST calendar day, not UTC', () => {
    expect(istToday(NOW)).toBe('2026-10-08');
    expect(istToday(Date.UTC(2026, 9, 7, 10, 0, 0))).toBe('2026-10-07');
  });

  it('shifts days across month boundaries', () => {
    expect(shiftDay('2026-10-01', -1)).toBe('2026-09-30');
    expect(shiftDay('2026-12-31', 1)).toBe('2027-01-01');
  });

  it('computes trailing presets inclusive of today', () => {
    expect(presetRange('7d', NOW)).toEqual({ from: '2026-10-02', to: '2026-10-08' });
    expect(rangeDays('2026-10-02', '2026-10-08')).toBe(7);
    expect(presetRange('30d', NOW).from).toBe('2026-09-09');
  });

  it('computes this/last month', () => {
    expect(presetRange('this_month', NOW)).toEqual({ from: '2026-10-01', to: '2026-10-08' });
    expect(presetRange('last_month', NOW)).toEqual({ from: '2026-09-01', to: '2026-09-30' });
    expect(presetRange('last_month', Date.UTC(2026, 0, 15))).toEqual({ from: '2025-12-01', to: '2025-12-31' });
    expect(presetRange('custom', NOW)).toBeNull();
  });

  it('validates ranges', () => {
    expect(isValidRange('2026-10-01', '2026-10-07')).toBe(true);
    expect(isValidRange('2026-10-08', '2026-10-07')).toBe(false);
    expect(isValidRange('', '2026-10-07')).toBe(false);
    expect(isValidRange('2024-01-01', '2026-10-07')).toBe(false);
  });

  it('matches the active preset chip', () => {
    expect(matchPreset('2026-10-02', '2026-10-08', NOW)).toBe('7d');
    expect(matchPreset('2026-10-03', '2026-10-08', NOW)).toBeNull();
  });
});
