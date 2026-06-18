import {
  buildDashboardAnalyticsParams,
  buildSnapshotDrillParams,
  buildVirtualCustomerDrillPath,
  isOperationalDrillTile,
} from './dashboardDrillDown';

describe('dashboardDrillDown', () => {
  it('builds analytics params for days and project', () => {
    expect(
      buildDashboardAnalyticsParams({ timeFilter: '7', projectFilter: 'ECR - Reserve 16', dateRange: null })
    ).toEqual({ days: 7, project: 'ECR - Reserve 16' });
  });

  it('builds snapshot params with project only', () => {
    expect(buildSnapshotDrillParams({ projectFilter: 'OMR - Vivriti' })).toEqual({
      project: 'OMR - Vivriti',
    });
    expect(buildSnapshotDrillParams({ projectFilter: 'all' })).toEqual({});
  });

  it('identifies operational drill tiles', () => {
    expect(isOperationalDrillTile('missed_follow_up')).toBe(true);
    expect(isOperationalDrillTile('total')).toBe(false);
    expect(isOperationalDrillTile('hot')).toBe(false);
  });

  it('operational drill path omits days filter', () => {
    const path = buildVirtualCustomerDrillPath('missed_follow_up', {
      timeFilter: '30',
      projectFilter: 'ECR - Reserve 16',
      dateRange: null,
    });
    expect(path).toContain('metric=missed_follow_up');
    expect(path).toContain('project=ECR');
    expect(path).not.toContain('days=');
  });

  it('cohort drill path includes days filter', () => {
    const path = buildVirtualCustomerDrillPath('hot', {
      timeFilter: '30',
      projectFilter: 'all',
      dateRange: null,
    });
    expect(path).toContain('days=30');
    expect(path).toContain('status=Nurturing');
    expect(path).toContain('temperature=Hot');
  });

  it('builds negotiation operational metric path', () => {
    const path = buildVirtualCustomerDrillPath('negotiation', {
      timeFilter: '7',
      projectFilter: 'all',
      dateRange: null,
    });
    expect(path).toContain('metric=negotiation');
    expect(path).not.toContain('days=');
  });

  it('builds qualified cohort metric path', () => {
    const path = buildVirtualCustomerDrillPath('qualified', {
      timeFilter: 'all',
      projectFilter: 'all',
      dateRange: null,
    });
    expect(path).toContain('metric=active_pipeline');
  });
});
