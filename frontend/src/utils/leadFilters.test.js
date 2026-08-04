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

  it('filtersMatchView includes mine scope', () => {
    const filters = { ...emptyLeadFilters(), mine: true, projects: ['A'] };
    const viewFilters = snapshotFiltersForView(filters, '');
    expect(filtersMatchView(filters, '', viewFilters)).toBe(true);
    expect(filtersMatchView({ ...filters, mine: false }, '', viewFilters)).toBe(false);
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

  it('parses and encodes sales_owners filter', () => {
    const params = new URLSearchParams('sales_owners=Anusha+O,Rep+B');
    const filters = filtersFromSearchParams(params);
    expect(filters.sales_owners).toEqual(['Anusha O', 'Rep B']);

    const encoded = filtersToSearchParams(
      { ...emptyLeadFilters(), sales_owners: ['Anusha O', 'Rep B'] },
      ''
    );
    expect(encoded.get('sales_owners')).toBe('Anusha O,Rep B');

    const listParams = buildLeadListParams({
      ...emptyLeadFilters(),
      sales_owners: ['Anusha O'],
    });
    expect(listParams.sales_owners).toBe('Anusha O');
    expect(countActiveFilters({ ...emptyLeadFilters(), sales_owners: ['Anusha O'] })).toBe(1);
  });

  it('maps date_field=updated to updated_from/to instead of created_*', () => {
    const fromUrl = filtersFromSearchParams(
      new URLSearchParams('date_field=updated&updated_from=2026-01-01&updated_to=2026-01-31')
    );
    expect(fromUrl.date_field).toBe('updated');
    expect(fromUrl.updated_from).toBe('2026-01-01');
    expect(fromUrl.updated_to).toBe('2026-01-31');

    const encoded = filtersToSearchParams(
      {
        ...emptyLeadFilters(),
        date_field: 'updated',
        updated_from: '2026-01-01',
        updated_to: '2026-01-31',
      },
      ''
    );
    expect(encoded.get('date_field')).toBe('updated');
    expect(encoded.get('updated_from')).toBe('2026-01-01');
    expect(encoded.get('updated_to')).toBe('2026-01-31');
    expect(encoded.get('created_from')).toBeNull();

    const listParams = buildLeadListParams({
      ...emptyLeadFilters(),
      date_field: 'updated',
      updated_from: '2026-01-01',
      updated_to: '2026-01-31',
    });
    expect(listParams.updated_from).toBe('2026-01-01');
    expect(listParams.updated_to).toBe('2026-01-31');
    expect(listParams.days).toBeUndefined();
    expect(listParams.created_from).toBeUndefined();
    expect(countActiveFilters({
      ...emptyLeadFilters(),
      date_field: 'updated',
      updated_from: '2026-01-01',
    })).toBe(1);
  });

  it('maps updated date_field days preset to updated_from/to', () => {
    const listParams = buildLeadListParams({
      ...emptyLeadFilters(),
      date_field: 'updated',
      days: '30',
    });
    expect(listParams.days).toBeUndefined();
    expect(listParams.updated_from).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(listParams.updated_to).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
