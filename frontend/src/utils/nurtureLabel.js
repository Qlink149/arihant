/** Nurture sub-labels — only valid when lead_status is Nurturing */

export const NURTURE_LABELS = ['Hot', 'Warm'];

export const NURTURING_STATUS = 'Nurturing';

export function isNurturingStatus(status) {
  return (status || '').trim().toLowerCase() === NURTURING_STATUS.toLowerCase();
}

export function formatStatusDisplay(status, temperature) {
  const label = status || '—';
  if (isNurturingStatus(label) && temperature) {
    return `Nurturing (${temperature})`;
  }
  return label;
}

export function getNurtureLabelVariant(temp) {
  switch (temp) {
    case 'Hot':
      return 'danger';
    case 'Warm':
      return 'warning';
    default:
      return 'neutral';
  }
}

/** @deprecated Use getNurtureLabelVariant + CrmBadge */
export function getNurtureLabelColor(temp) {
  const variant = getNurtureLabelVariant(temp);
  return `crm-badge crm-badge--${variant}`;
}
