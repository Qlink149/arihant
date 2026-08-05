import {
  getTimelineForDisplay,
  TIMELINE_INITIAL_VISIBLE,
  TIMELINE_LOAD_MORE_STEP,
} from './contextUpdates';

describe('getTimelineForDisplay', () => {
  it('returns entries newest-first by timestamp', () => {
    const updates = [
      { type: 'note', description: 'Oldest', timestamp: '2024-01-01T00:00:00Z' },
      { type: 'task', description: 'Middle', timestamp: '2024-06-01T00:00:00Z' },
      { type: 'note', description: 'Newest', timestamp: '2024-12-01T00:00:00Z' },
    ];
    const timeline = getTimelineForDisplay(updates);
    expect(timeline.map((u) => u.description)).toEqual(['Newest', 'Middle', 'Oldest']);
  });

  it('supports pagination slice: newest in first page', () => {
    const updates = Array.from({ length: 20 }, (_, i) => ({
      type: 'note',
      description: `Event ${i}`,
      timestamp: `2024-01-${String(i + 1).padStart(2, '0')}T12:00:00Z`,
    }));
    const timeline = getTimelineForDisplay(updates);
    const firstPage = timeline.slice(0, TIMELINE_INITIAL_VISIBLE);
    expect(firstPage).toHaveLength(TIMELINE_INITIAL_VISIBLE);
    expect(firstPage[0].description).toBe('Event 19');

    const secondPage = timeline.slice(0, TIMELINE_INITIAL_VISIBLE + TIMELINE_LOAD_MORE_STEP);
    expect(secondPage).toHaveLength(20);
    expect(secondPage[secondPage.length - 1].description).toBe('Event 0');
  });

  it('prefers _mongo_index over display order for edit PATCH', () => {
    const updates = [
      { type: 'created', description: 'Lead created', timestamp: '2024-01-01T00:00:00Z', _mongo_index: 0 },
      { type: 'note', description: 'Older note', timestamp: '2024-06-01T00:00:00Z', _mongo_index: 1 },
      { type: 'note', description: 'Newest note', timestamp: '2024-12-01T00:00:00Z', _mongo_index: 2 },
    ];
    const timeline = getTimelineForDisplay(updates);
    expect(timeline[0].description).toBe('Newest note');
    expect(timeline[0]._source_index).toBe(2);
    expect(timeline[1]._source_index).toBe(1);
  });
});
