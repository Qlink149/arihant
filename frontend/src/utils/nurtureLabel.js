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

export function getNurtureLabelColor(temp) {
  switch (temp) {
    case 'Hot':
      return 'text-red-500 bg-red-500/20';
    case 'Warm':
      return 'text-orange-500 bg-orange-500/20';
    default:
      return 'text-gray-500 bg-gray-500/20';
  }
}
