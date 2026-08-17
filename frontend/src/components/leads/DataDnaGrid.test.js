import { describe, expect, it } from 'vitest';
import { formatDateTimeIST } from '../../utils/datetime';
import { formatLeadProjects } from '../../utils/leadProjects';

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
