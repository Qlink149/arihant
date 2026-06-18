import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { addIstDays, formatIstYmd } from './datetime';
import { buildQuarterOptions, formatLocalDate } from './salesPeriodFilter';

describe('IST sales period helpers', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-06-17T20:30:00.000Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('formatIstYmd uses IST calendar day', () => {
    expect(formatIstYmd()).toBe('2026-06-18');
  });

  it('addIstDays shifts IST calendar dates', () => {
    expect(addIstDays(-1)).toBe('2026-06-17');
  });

  it('buildQuarterOptions uses IST current quarter', () => {
    const options = buildQuarterOptions();
    expect(options.some((o) => o.value === 'current')).toBe(true);
    expect(options.some((o) => o.label.includes('Q2 2026'))).toBe(true);
  });

  it('formatLocalDate returns IST ymd string', () => {
    expect(formatLocalDate(new Date())).toBe('2026-06-18');
  });
});
