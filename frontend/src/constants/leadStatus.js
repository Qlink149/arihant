/** SLA-aligned lead statuses (mirrors backend UI_LEAD_STATUSES). */

export const UI_LEAD_STATUSES = [
  'New',
  'RNR',
  'Contacted',
  'Nurturing',
  'Site Visit Scheduled',
  'Visit Completed',
  'SV Completed – Follow Up',
  'Negotiation',
  'Gone Cold',
  'Future Prospect',
  'Re-engaged',
  'Closed Won',
  'Closed Lost',
];

/** Alias for components that import LEAD_STATUSES */
export const LEAD_STATUSES = UI_LEAD_STATUSES;
