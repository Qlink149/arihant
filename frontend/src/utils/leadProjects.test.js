/**
 * @vitest-environment jsdom
 */
import { describe, it, expect } from 'vitest';
import { getLeadProjects, formatLeadProjects, primaryLeadProject } from './leadProjects';
import { isMultiSelectWithOtherEmpty } from '../components/ui/MultiSelectWithOther';

describe('leadProjects', () => {
  it('prefers projects array', () => {
    expect(getLeadProjects({ projects: ['A', 'B'], project: 'Z' })).toEqual(['A', 'B']);
  });

  it('falls back to semicolon split', () => {
    expect(getLeadProjects({ project: 'ECR - Reserve 16; OMR - Vivriti' })).toEqual([
      'ECR - Reserve 16',
      'OMR - Vivriti',
    ]);
  });

  it('returns empty for missing project', () => {
    expect(getLeadProjects({})).toEqual([]);
    expect(formatLeadProjects({})).toBe('—');
  });

  it('formats joined names', () => {
    expect(formatLeadProjects({ projects: ['A', 'B'] })).toBe('A; B');
    expect(primaryLeadProject({ projects: ['A', 'B'] })).toBe('A');
  });
});

describe('isMultiSelectWithOtherEmpty', () => {
  it('treats missing and empty arrays as empty', () => {
    expect(isMultiSelectWithOtherEmpty(undefined)).toBe(true);
    expect(isMultiSelectWithOtherEmpty([])).toBe(true);
    expect(isMultiSelectWithOtherEmpty(['A'])).toBe(false);
  });
});
