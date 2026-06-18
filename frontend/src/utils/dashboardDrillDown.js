/**
 * Build Virtual Customer URL from main dashboard stat drill-down (org-wide).
 */

function formatYmd(date) {
  if (!date) return '';
  const d = date instanceof Date ? date : new Date(date);
  if (Number.isNaN(d.getTime())) return '';
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/** Operational tiles use snapshot drill-down (project only, no created-date window). */
export const OPERATIONAL_DRILL_TILES = new Set([
  'missed_follow_up',
  'todays_site_visits',
  'rnr',
  'negotiation',
  'follow_up_today',
  'todays_leads',
]);

export function isOperationalDrillTile(tile) {
  return OPERATIONAL_DRILL_TILES.has(tile);
}

export function buildDashboardAnalyticsParams({ timeFilter, dateRange, projectFilter }) {
  const params = {};
  if (projectFilter && projectFilter !== 'all') {
    params.project = projectFilter;
  }
  if (timeFilter === '7' || timeFilter === '15' || timeFilter === '30') {
    params.days = parseInt(timeFilter, 10);
  } else if (timeFilter === 'custom' && dateRange?.from) {
    params.created_from = formatYmd(dateRange.from);
    if (dateRange.to) {
      params.created_to = formatYmd(dateRange.to);
    } else {
      params.created_to = formatYmd(dateRange.from);
    }
  }
  return params;
}

export function buildSnapshotDrillParams({ projectFilter }) {
  const params = {};
  if (projectFilter && projectFilter !== 'all') {
    params.project = projectFilter;
  }
  return params;
}

export function buildVirtualCustomerDrillPath(tile, dashboardFilters) {
  const params = new URLSearchParams();
  const isOperational = isOperationalDrillTile(tile);
  const analytics = isOperational
    ? buildSnapshotDrillParams(dashboardFilters)
    : buildDashboardAnalyticsParams(dashboardFilters);

  if (analytics.project) params.set('project', analytics.project);
  if (!isOperational) {
    if (analytics.days) params.set('days', String(analytics.days));
    if (analytics.created_from) params.set('created_from', analytics.created_from);
    if (analytics.created_to) params.set('created_to', analytics.created_to);
  }

  switch (tile) {
    case 'missed_follow_up':
      params.set('metric', 'missed_follow_up');
      break;
    case 'todays_site_visits':
      params.set('metric', 'todays_site_visits');
      break;
    case 'rnr':
      params.set('metric', 'rnr');
      break;
    case 'negotiation':
      params.set('metric', 'negotiation');
      break;
    case 'follow_up_today':
      params.set('metric', 'follow_up_today');
      break;
    case 'todays_leads':
      params.set('metric', 'todays_leads');
      break;
    case 'dormant':
      params.set('dormant', '1');
      break;
    case 'vip':
      params.set('vip', 'true');
      break;
    case 'hot':
      params.set('status', 'Nurturing');
      params.set('temperature', 'Hot');
      break;
    case 'qualified':
    case 'active_pipeline':
      params.set('metric', 'active_pipeline');
      break;
    case 'total':
    default:
      break;
  }

  const qs = params.toString();
  return qs ? `/virtual-customer?${qs}` : '/virtual-customer';
}
