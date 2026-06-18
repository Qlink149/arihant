import { describe, expect, it } from 'vitest';
import {
  isOtherModeWithEmptyText,
  normalizeOptions,
  resolveSelectWithOtherState,
  resolveSelectWithOtherValue,
} from './selectWithOther';

describe('selectWithOther', () => {
  it('normalizeOptions accepts strings and objects with name', () => {
    expect(normalizeOptions(['A', { name: 'B' }, ''])).toEqual(['A', 'B']);
  });

  it('resolves preset mode when value is in options', () => {
    const state = resolveSelectWithOtherState('Chennai', ['Chennai', 'OMR']);
    expect(state).toEqual({ mode: 'preset', presetValue: 'Chennai', otherText: '' });
  });

  it('resolves other mode when value is not in options', () => {
    const state = resolveSelectWithOtherState('Custom Area', ['Chennai', 'OMR']);
    expect(state).toEqual({ mode: 'other', presetValue: '', otherText: 'Custom Area' });
  });

  it('resolves empty preset when value is empty', () => {
    const state = resolveSelectWithOtherState('', ['Chennai']);
    expect(state).toEqual({ mode: 'preset', presetValue: '', otherText: '' });
  });

  it('resolveSelectWithOtherValue returns trimmed other text in other mode', () => {
    expect(resolveSelectWithOtherValue('other', '', '  My Project  ')).toBe('My Project');
    expect(resolveSelectWithOtherValue('preset', '1-2 Cr', 'ignored')).toBe('1-2 Cr');
  });

  it('isOtherModeWithEmptyText detects incomplete other selection', () => {
    expect(isOtherModeWithEmptyText('other', '')).toBe(true);
    expect(isOtherModeWithEmptyText('other', '  ')).toBe(true);
    expect(isOtherModeWithEmptyText('other', 'Valid')).toBe(false);
    expect(isOtherModeWithEmptyText('preset', '')).toBe(false);
  });
});
