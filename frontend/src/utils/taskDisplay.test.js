import {
  getTaskDueBucket,
  getTaskDisplayTitle,
  getDueStatusBadge,
  getPriorityBadge,
  getTaskReason,
} from './taskDisplay';

describe('getTaskDueBucket', () => {
  const realToday = Date.prototype.toISOString;

  afterEach(() => {
    Date.prototype.toISOString = realToday;
  });

  it('classifies overdue, today, and upcoming', () => {
    Date.prototype.toISOString = () => '2026-05-29T12:00:00.000Z';
    expect(getTaskDueBucket('2026-05-28')).toBe('overdue');
    expect(getTaskDueBucket('2026-05-29')).toBe('due_today');
    expect(getTaskDueBucket('2026-06-01')).toBe('upcoming');
    expect(getTaskDueBucket('')).toBe('none');
  });
});

describe('getTaskDisplayTitle', () => {
  it('puts lead first for generic SLA titles', () => {
    const title = getTaskDisplayTitle({
      description: 'Reassign Lead',
      lead_name: 'Rajesh Kumar',
    });
    expect(title).toBe('Rajesh Kumar — Reassign Lead');
  });

  it('appends lead for user action titles', () => {
    const title = getTaskDisplayTitle({
      description: 'Follow-up call',
      lead_name: 'Rajesh Kumar',
    });
    expect(title).toBe('Follow-up call · Rajesh Kumar');
  });
});

describe('badges', () => {
  it('returns overdue badge styling', () => {
    const badge = getDueStatusBadge('overdue');
    expect(badge.label).toBe('Overdue');
    expect(badge.className).toMatch(/red/);
  });

  it('returns priority colors', () => {
    expect(getPriorityBadge('high').className).toMatch(/red/);
    expect(getPriorityBadge('medium').className).toMatch(/amber/);
    expect(getPriorityBadge('low').className).toMatch(/gray/);
  });
});

describe('getTaskReason', () => {
  it('prefers task_reason over latest_note', () => {
    expect(
      getTaskReason({ task_reason: 'SLA note', latest_note: 'Other' })
    ).toBe('SLA note');
  });
});
