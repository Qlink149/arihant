export const LOGGED_OUTCOMES = [
  'Interested',
  'Needs Time',
  'Call Back Later',
  'Follow-up Scheduled',
  'Switched Off',
  'RNR',
  'Others',
  'Not Interested',
];

export const OUTCOME_GROUPS = {
  Interested: 'positive',
  'Needs Time': 'neutral',
  'Call Back Later': 'neutral',
  'Follow-up Scheduled': 'neutral',
  'Switched Off': 'neutral',
  RNR: 'neutral',
  Others: 'neutral',
  'Not Interested': 'negative',
};

export const OUTCOME_STATUSES = ['Contacted', 'Nurturing'];

export function isOutcomeStatus(status) {
  return OUTCOME_STATUSES.includes(String(status || '').trim());
}
