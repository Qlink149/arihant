import { describe, expect, it } from 'vitest';
import {
  extractMentionTokens,
  findActiveMention,
  insertMentionAtCaret,
  missingMentionNames,
  splitMentionSegments,
  syncMentionIdsFromText,
} from './noteMentions';

describe('findActiveMention', () => {
  it('detects @query at end', () => {
    expect(findActiveMention('Hi @Anu', 7)).toEqual({ start: 3, end: 7, query: 'Anu' });
  });

  it('returns null when not in a mention', () => {
    expect(findActiveMention('Hello there', 11)).toBeNull();
  });
});

describe('insertMentionAtCaret', () => {
  it('replaces active query with @Full Name', () => {
    const { text, caret } = insertMentionAtCaret('Please @Anu', 11, 'Anusha Omprakash');
    expect(text).toBe('Please @Anusha Omprakash ');
    expect(caret).toBe('Please @Anusha Omprakash '.length);
  });
});

describe('extractMentionTokens / sync', () => {
  it('extracts multi-word names', () => {
    expect(extractMentionTokens('cc @Anusha Omprakash thanks')).toEqual(['Anusha Omprakash']);
  });

  it('syncs ids from text and force-add', () => {
    const agents = [
      { id: 'a1', full_name: 'Anusha Omprakash' },
      { id: 'a2', full_name: 'Jigar' },
    ];
    expect(
      syncMentionIdsFromText(agents, [], 'Ping @Anusha Omprakash', ['a1'])
    ).toEqual(['a1']);
    expect(syncMentionIdsFromText(agents, ['a1', 'a2'], 'no mentions left', [])).toEqual([]);
  });
});

describe('splitMentionSegments / legacy', () => {
  it('splits text and mention segments', () => {
    expect(splitMentionSegments('Hi @Admin please')).toEqual([
      { type: 'text', value: 'Hi ' },
      { type: 'mention', value: '@Admin' },
      { type: 'text', value: ' please' },
    ]);
  });

  it('lists mentioned_names missing from body', () => {
    expect(missingMentionNames('Kindly follow up', ['Anusha Omprakash'])).toEqual([
      'Anusha Omprakash',
    ]);
    expect(missingMentionNames('Ping @Anusha Omprakash', ['Anusha Omprakash'])).toEqual([]);
  });
});
