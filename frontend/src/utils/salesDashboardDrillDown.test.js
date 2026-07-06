import { buildSalesVirtualCustomerPath } from './salesDashboardDrillDown';
import { salesPeriodToLeadDateParams } from './salesPeriodFilter';

describe('salesDashboardDrillDown', () => {
  it('builds org-wide hot nurture path with period', () => {
    const path = buildSalesVirtualCustomerPath('hot', {
      quarter: 'all',
      datePeriod: { days: '30' },
    });
    expect(path).toContain('/virtual-customer?');
    expect(path).toContain('days=30');
    expect(path).toContain('status=Nurturing');
    expect(path).toContain('temperature=Hot');
  });

  it('builds agent-scoped rnr path', () => {
    const path = buildSalesVirtualCustomerPath('rnr', {
      quarter: 'all',
      agentName: 'Roshini',
    });
    expect(path).toContain('metric=rnr');
    expect(path).toContain('agent=Roshini');
  });

  it('builds site visit stage metric path', () => {
    const path = buildSalesVirtualCustomerPath('site_visits', { quarter: 'all' });
    expect(path).toContain('metric=site_visits');
  });

  it('resolves quarter to created date range', () => {
    const period = salesPeriodToLeadDateParams({ quarter: '2026-Q1' });
    expect(period).toEqual({ created_from: '2026-01-01', created_to: '2026-03-31' });
  });
});
