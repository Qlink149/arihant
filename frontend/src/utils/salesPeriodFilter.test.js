import { describe, expect, it } from 'vitest';
import {
  buildSalesDashboardParams,
  getSalesPeriodLabel,
  isDatePeriodActive,
} from './salesPeriodFilter';

describe('salesPeriodFilter', () => {
  it('builds quarter params when quarter is set', () => {
    expect(buildSalesDashboardParams({ quarter: '2026-Q1', datePeriod: { days: '7' } })).toEqual({
      quarter: '2026-Q1',
    });
  });

  it('builds days params when no quarter', () => {
    expect(buildSalesDashboardParams({ quarter: 'all', datePeriod: { days: '30' } })).toEqual({
      days: 30,
    });
  });

  it('builds date range params', () => {
    expect(
      buildSalesDashboardParams({
        quarter: 'all',
        datePeriod: { created_from: '2026-06-01', created_to: '2026-06-17' },
      })
    ).toEqual({
      created_from: '2026-06-01',
      created_to: '2026-06-17',
    });
  });

  it('labels quarter and date periods', () => {
    expect(getSalesPeriodLabel({ quarter: '2026-Q1' })).toContain('Q1 2026');
    expect(getSalesPeriodLabel({ datePeriod: { days: '7' } })).toBe('Last 7 days');
    expect(
      getSalesPeriodLabel({ datePeriod: { created_from: '2026-06-17', created_to: '2026-06-17' } })
    ).toBe('2026-06-17');
  });

  it('detects active date period', () => {
    expect(isDatePeriodActive({})).toBe(false);
    expect(isDatePeriodActive({ days: '7' })).toBe(true);
    expect(isDatePeriodActive({ created_from: '2026-01-01' })).toBe(true);
  });
});
