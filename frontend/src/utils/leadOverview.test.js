import { buildVirtualCustomerPath } from './leadOverview';

describe('leadOverview', () => {
  it('buildVirtualCustomerPath scopes to rep pipeline for My Dashboard drill-down', () => {
    const path = buildVirtualCustomerPath({ metric: 'missed_follow_up' });
    expect(path).toContain('metric=missed_follow_up');
    expect(path).toContain('mine=1');
  });

  it('buildVirtualCustomerPath returns bare path without metric', () => {
    expect(buildVirtualCustomerPath({})).toBe('/virtual-customer');
  });
});
