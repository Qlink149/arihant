import {
  shouldUseVirtualList,
  VIRTUAL_LIST_THRESHOLD,
  USE_VIRTUAL_LIST,
} from './performanceFlags';

describe('shouldUseVirtualList', () => {
  it('returns false below threshold', () => {
    expect(shouldUseVirtualList(VIRTUAL_LIST_THRESHOLD - 1)).toBe(false);
  });

  it('returns true at threshold when flag enabled', () => {
    if (USE_VIRTUAL_LIST) {
      expect(shouldUseVirtualList(VIRTUAL_LIST_THRESHOLD)).toBe(true);
    }
  });
});
