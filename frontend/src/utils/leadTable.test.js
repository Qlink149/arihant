import {
  buildEarliestPendingTaskMap,
  buildPendingTaskMap,
  formatFollowUp,
} from './leadTable';

describe('buildPendingTaskMap', () => {
  it('counts pending tasks per lead', () => {
    const map = buildPendingTaskMap([
      { lead_id: 'a', status: 'pending' },
      { lead_id: 'a', status: 'pending' },
      { lead_id: 'b', status: 'completed' },
      { lead_id: 'c', status: 'pending' },
    ]);
    expect(map.get('a')).toBe(2);
    expect(map.get('b')).toBeUndefined();
    expect(map.get('c')).toBe(1);
  });
});

describe('buildEarliestPendingTaskMap', () => {
  it('keeps earliest due_date per lead', () => {
    const map = buildEarliestPendingTaskMap([
      { id: 't2', lead_id: 'L1', status: 'pending', due_date: '2026-06-10' },
      { id: 't1', lead_id: 'L1', status: 'pending', due_date: '2026-06-05' },
      { id: 't3', lead_id: 'L2', status: 'pending', due_date: '2026-06-01' },
      { id: 't4', lead_id: 'L1', status: 'completed', due_date: '2026-01-01' },
      { id: 't5', lead_id: 'L3', status: 'pending' },
    ]);
    expect(map.get('L1')?.id).toBe('t1');
    expect(map.get('L2')?.id).toBe('t3');
    expect(map.has('L3')).toBe(false);
  });
});

describe('formatFollowUp', () => {
  it('prefers next_action_date on lead', () => {
    const label = formatFollowUp(
      { id: 'x', next_action_date: '2026-06-01T10:00:00Z' },
      [],
      new Map()
    );
    expect(label).toBeTruthy();
  });

  it('uses earliestTaskMap when no next_action_date', () => {
    const taskMap = new Map([['L1', 1]]);
    const earliestTaskMap = new Map([
      ['L1', { due_date: '2026-06-15', due_time: '14:30' }],
    ]);
    const label = formatFollowUp({ id: 'L1' }, [], taskMap, earliestTaskMap);
    expect(label).toContain('2026');
  });
});
