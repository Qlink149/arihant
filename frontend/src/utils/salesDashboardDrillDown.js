/**
 * Build Virtual Customer URL from Sales Team Dashboard stat drill-down.
 */

import { salesPeriodToLeadDateParams } from './salesPeriodFilter';

/** @typedef {'total'|'hot'|'warm'|'negotiation'|'rnr'|'site_visits'|'deals_won'|'deals_lost'} SalesDrillStat */

const STAT_QUERY = {
  total: {},
  hot: { status: 'Nurturing', temperature: 'Hot' },
  warm: { status: 'Nurturing', temperature: 'Warm' },
  negotiation: { metric: 'negotiation' },
  rnr: { metric: 'rnr' },
  contacted: { metric: 'contacted' },
  site_visits: { metric: 'site_visits' },
  deals_won: { metric: 'deals_won' },
  deals_lost: { metric: 'deals_lost' },
};

/**
 * @param {SalesDrillStat|string} statKey
 * @param {{ quarter?: string, datePeriod?: object, agentName?: string|null }} options
 */
export function buildSalesVirtualCustomerPath(statKey, { quarter, datePeriod, agentName } = {}) {
  const params = new URLSearchParams();
  const period = salesPeriodToLeadDateParams({ quarter, datePeriod });
  if (period.days) params.set('days', String(period.days));
  if (period.created_from) params.set('created_from', period.created_from);
  if (period.created_to) params.set('created_to', period.created_to);

  const stat = STAT_QUERY[statKey] || {};
  if (stat.metric) params.set('metric', stat.metric);
  if (stat.status) params.set('status', stat.status);
  if (stat.temperature) params.set('temperature', stat.temperature);

  const agent = (agentName || '').trim();
  if (agent) params.set('agent', agent);

  const qs = params.toString();
  return qs ? `/virtual-customer?${qs}` : '/virtual-customer';
}

export const SALES_DRILLABLE_STATS = Object.keys(STAT_QUERY);
