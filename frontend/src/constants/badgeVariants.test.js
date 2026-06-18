import { describe, expect, it } from 'vitest';
import {
  getNotificationUrgencyLabel,
  getNotificationUrgencyVariant,
  getStatusBadgeVariant,
} from './badgeVariants';

describe('badgeVariants', () => {
  it('maps lead statuses to semantic variants', () => {
    expect(getStatusBadgeVariant('New')).toBe('new');
    expect(getStatusBadgeVariant('Won')).toBe('success');
    expect(getStatusBadgeVariant('RNR')).toBe('danger');
    expect(getStatusBadgeVariant('Site Visit Scheduled')).toBe('purple');
    expect(getStatusBadgeVariant('Unknown Status')).toBe('neutral');
    expect(getStatusBadgeVariant(null)).toBe('neutral');
  });

  it('maps notification urgency to variants', () => {
    expect(getNotificationUrgencyVariant({ urgency: 'urgent' })).toBe('danger');
    expect(getNotificationUrgencyVariant({ severity: 'high' })).toBe('danger');
    expect(getNotificationUrgencyVariant({ urgency: 'action_needed' })).toBe('warning');
    expect(getNotificationUrgencyVariant({ severity: 'medium' })).toBe('warning');
    expect(getNotificationUrgencyVariant({})).toBe('neutral');
  });

  it('returns urgency labels', () => {
    expect(getNotificationUrgencyLabel({ urgency: 'urgent' })).toBe('Urgent');
    expect(getNotificationUrgencyLabel({ urgency: 'action_needed' })).toBe('Action Needed');
    expect(getNotificationUrgencyLabel({})).toBe('Info');
  });
});
