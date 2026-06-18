import { describe, expect, it } from 'vitest';
import {
  buildLeadListParams,
  countActiveFilters,
  emptyLeadFilters,
  filtersFromSearchParams,
  filtersMatchView,
  filtersToSearchParams,
  formatMultiLabel,
  snapshotFiltersForView,
} from './leadFilters';

describe('leadFilters', () => {
  it('parses legacy single-value URL params into arrays', () => {
    const params = new URLSearchParams('project=Tower+A&location=Chennai&status=New');
    const filters = filtersFromSearchParams(params);
    expect(filters.projects).toEqual(['Tower A']);
    expect(filters.locations).toEqual(['Chennai']);
    expect(filters.statuses).toEqual(['New']);
  });

  it('encodes multi-value filters as comma-separated URL params', () => {
    const filters = {
      ...emptyLeadFilters(),
      projects: ['A', 'B'],
      budgets: ['1-2 Cr'],
    };
    const params = filtersToSearchParams(filters, '');
    expect(params.get('projects')).toBe('A,B');
    expect(params.get('budgets')).toBe('1-2 Cr');
  });

  it('buildLeadListParams sends comma-separated multi filters', () => {
    const filters = {
      ...emptyLeadFilters(),
      projects: ['Proj A', 'Proj B'],
      locations: ['Chennai'],
    };
    const params = buildLeadListParams(filters, 'john');
    expect(params.projects).toBe('Proj A,Proj B');
    expect(params.locations).toBe('Chennai');
    expect(params.search).toBe('john');
  });

  it('countActiveFilters counts array fields once each', () => {
    const filters = {
      ...emptyLeadFilters(),
      projects: ['A', 'B'],
      budgets: ['1-2 Cr'],
      vip: true,
      days: '30',
    };
    expect(countActiveFilters(filters)).toBe(4);
  });

  it('filtersMatchView compares full snapshot including search', () => {
    const filters = { ...emptyLeadFilters(), projects: ['A'] };
    const viewFilters = snapshotFiltersForView(filters, 'test');
    expect(filtersMatchView(filters, 'test', viewFilters)).toBe(true);
    expect(filtersMatchView(filters, 'other', viewFilters)).toBe(false);
  });

  it('formatMultiLabel shows count for multiple selections', () => {
    expect(formatMultiLabel([], 'Project')).toBe('Project');
    expect(formatMultiLabel(['A'], 'Project')).toBe('A');
    expect(formatMultiLabel(['A', 'B'], 'Project')).toBe('Project (2)');
  });

  it('parses meta_qualified URL param', () => {
    const params = new URLSearchParams('sources=facebook_ad,website&meta_qualified=1');
    const filters = filtersFromSearchParams(params);
    expect(filters.sources).toEqual(['facebook_ad', 'website']);
    expect(filters.meta_qualified).toBe(true);
  });

  it('buildLeadListParams includes meta_qualified and sources', () => {
    const filters = {
      ...emptyLeadFilters(),
      sources: ['google ads'],
      meta_qualified: false,
    };
    const params = buildLeadListParams(filters, '');
    expect(params.sources).toBe('google ads');
    expect(params.meta_qualified).toBe(false);
  });
});
