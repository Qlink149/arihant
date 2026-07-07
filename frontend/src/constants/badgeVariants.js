/** Semantic badge variant names — map to .crm-badge--{variant} CSS classes */

export const STATUS_VARIANTS = {
  New: 'new',
  Open: 'info',
  Contacted: 'sky',
  'Follow Up': 'amber',
  'Follow Up 1': 'amber',
  'Follow Up 2': 'amber',
  Interested: 'cyan',
  Junk: 'neutral',
  Unqualified: 'neutral',
  'Site Visit': 'purple',
  'Site Visit Scheduled': 'purple',
  'Visit Completed': 'success',
  'SV Follow-up 1': 'teal',
  'SV Follow-up 2': 'cyan',
  'Re-engaged': 'cyan',
  'Advance Paid': 'emerald',
  Negotiation: 'amber',
  RNR: 'danger',
  Nurturing: 'orange',
  'Gone Cold': 'neutral',
  Lost: 'neutral',
  Won: 'success',
};

export function getStatusBadgeVariant(status) {
  if (!status) return 'neutral';
  if (status === 'New' || /^new$/i.test(status)) return 'new';
  return STATUS_VARIANTS[status] || 'neutral';
}

export function getNotificationUrgencyVariant(notification) {
  const n = notification || {};
  if (n.urgency === 'urgent' || n.severity === 'high') return 'danger';
  if (n.urgency === 'action_needed' || n.severity === 'medium') return 'warning';
  return 'neutral';
}

export function getNotificationUrgencyLabel(notification) {
  const variant = getNotificationUrgencyVariant(notification);
  if (variant === 'danger') return 'Urgent';
  if (variant === 'warning') return 'Action Needed';
  return 'Info';
}
