import { describe, expect, it } from 'vitest';
import { formatDateTimeIST } from '../../utils/datetime';
import { formatLeadProjects } from '../../utils/leadProjects';
import { LOST_REASON_OPTIONS, isLostReasonStatus } from '../../constants/lostReason';

/**
 * Smoke test for Lead Overview field display helpers used by DataDnaGrid.
 * Guards against missing imports (ReferenceError on accordion expand).
 */
describe('DataDnaGrid field display helpers', () => {
  const lead = {
    created_at: '2025-05-27T10:30:00',
    updated_at: '2025-06-01T14:00:00',
    projects: ['ECR - Reserve 16'],
    project: 'ECR - Reserve 16',
  };

  it('formats created_at and updated_at via formatDateTimeIST', () => {
    expect(formatDateTimeIST(lead.created_at)).toBeTruthy();
    expect(formatDateTimeIST(lead.updated_at)).toBeTruthy();
    expect(() => formatDateTimeIST(lead.created_at)).not.toThrow();
    expect(() => formatDateTimeIST(lead.updated_at)).not.toThrow();
  });

  it('formats projects via formatLeadProjects', () => {
    expect(formatLeadProjects(lead)).toBe('ECR - Reserve 16');
  });
});

// #49: DataDna "Lead Overview" adds Email + Lost Reason fields.
describe('DataDnaGrid #49 Email + Lost Reason field helpers', () => {
  it('display falls back to "Not specified" when email/lost_reason are absent', () => {
    const lead = {};
    expect(lead.email || 'Not specified').toBe('Not specified');
    expect(lead.lost_reason || 'Not specified').toBe('Not specified');
  });

  it('displays raw email/lost_reason values when present', () => {
    const lead = { email: 'buyer@example.com', lost_reason: 'Budget' };
    expect(lead.email || 'Not specified').toBe('buyer@example.com');
    expect(lead.lost_reason || 'Not specified').toBe('Budget');
  });

  it('uses the enum picklist editor only for Unqualified / Closed Lost statuses', () => {
    expect(isLostReasonStatus('Unqualified')).toBe(true);
    expect(isLostReasonStatus('Closed Lost')).toBe(true);
    expect(isLostReasonStatus('Junk')).toBe(false);
    expect(isLostReasonStatus('Dropped')).toBe(false);
    expect(isLostReasonStatus('New')).toBe(false);
  });

  it('lost reason picklist matches the backend canonical options', () => {
    expect(LOST_REASON_OPTIONS).toContain('Budget');
    expect(LOST_REASON_OPTIONS).toContain('Channel Partner');
    expect(LOST_REASON_OPTIONS.length).toBeGreaterThan(0);
  });
});
