/**
 * Virtual Customer lead filter state, URL sync, and API param helpers.
 */

import { addIstDays, formatIstYmd } from './datetime';

const MULTI_FILTER_KEYS = ['budgets', 'locations', 'projects', 'statuses', 'sources', 'sales_owners'];

const parseCommaList = (value) => {
  if (!value || !String(value).trim()) return [];
  return String(value)
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean);
};

const encodeCommaList = (values) => {
  if (!Array.isArray(values) || values.length === 0) return '';
  return values.map((v) => String(v).trim()).filter(Boolean).join(',');
};

const parseMetaQualified = (value) => {
  if (value === '1' || value === 'true') return true;
  if (value === '0' || value === 'false') return false;
  return null;
};

const normalizeDateField = (value) => (value === 'updated' ? 'updated' : 'created');

export const emptyLeadFilters = () => ({
  budgets: [],
  locations: [],
  projects: [],
  statuses: [],
  sources: [],
  sales_owners: [],
  intent: '',
  vip: null,
  re_enquiry: null,
  nudge_pending: null,
  temperature: '',
  days: '',
  created_from: '',
  created_to: '',
  updated_from: '',
  updated_to: '',
  date_field: 'created', // 'created' | 'updated' for VC date filter mode
  meta_qualified: null,
  metric: '',
  dormant: false,
  mine: false,
});

/** Migrate legacy single-value URL params to array fields. */
export const filtersFromSearchParams = (searchParams) => {
  const base = emptyLeadFilters();

  const budgets = parseCommaList(searchParams.get('budgets') || searchParams.get('budget'));
  const locations = parseCommaList(searchParams.get('locations') || searchParams.get('location'));
  const projects = parseCommaList(searchParams.get('projects') || searchParams.get('project'));
  const statuses = parseCommaList(searchParams.get('statuses') || searchParams.get('status'));
  const sources = parseCommaList(searchParams.get('sources') || searchParams.get('source'));
  const sales_owners = parseCommaList(
    searchParams.get('sales_owners') || searchParams.get('sales_owner')
  );

  const vipRaw = searchParams.get('vip');
  let vip = null;
  if (vipRaw === '1' || vipRaw === 'true') vip = true;
  if (vipRaw === '0' || vipRaw === 'false') vip = false;

  const reEnquiryRaw = searchParams.get('re_enquiry');
  let re_enquiry = null;
  if (reEnquiryRaw === '1' || reEnquiryRaw === 'true') re_enquiry = true;
  if (reEnquiryRaw === '0' || reEnquiryRaw === 'false') re_enquiry = false;

  const nudgeRaw = searchParams.get('nudge') || searchParams.get('nudge_pending');
  let nudge_pending = null;
  if (nudgeRaw === '1' || nudgeRaw === 'true') nudge_pending = true;
  if (nudgeRaw === '0' || nudgeRaw === 'false') nudge_pending = false;

  const updated_from = searchParams.get('updated_from') || '';
  const updated_to = searchParams.get('updated_to') || '';
  const dateFieldRaw = searchParams.get('date_field');
  let date_field = normalizeDateField(dateFieldRaw);
  if (!dateFieldRaw && (updated_from || updated_to)) {
    date_field = 'updated';
  }

  return {
    ...base,
    budgets,
    locations,
    projects,
    statuses,
    sources,
    sales_owners,
    intent: searchParams.get('intent') || '',
    vip,
    re_enquiry,
    nudge_pending,
    temperature: searchParams.get('temperature') || '',
    days: searchParams.get('days') || '',
    created_from: searchParams.get('created_from') || '',
    created_to: searchParams.get('created_to') || '',
    updated_from,
    updated_to,
    date_field,
    meta_qualified: parseMetaQualified(searchParams.get('meta_qualified')),
    metric: searchParams.get('metric') || '',
    dormant: searchParams.get('dormant') === '1' || searchParams.get('dormant') === 'true',
    mine: searchParams.get('mine') === '1' || searchParams.get('mine') === 'true',
  };
};

export const filtersToSearchParams = (filters, agentQuery) => {
  const params = new URLSearchParams();
  const dateField = normalizeDateField(filters.date_field);

  const budgets = encodeCommaList(filters.budgets);
  const locations = encodeCommaList(filters.locations);
  const projects = encodeCommaList(filters.projects);
  const statuses = encodeCommaList(filters.statuses);
  const sources = encodeCommaList(filters.sources);
  const sales_owners = encodeCommaList(filters.sales_owners);

  if (budgets) params.set('budgets', budgets);
  if (locations) params.set('locations', locations);
  if (projects) params.set('projects', projects);
  if (statuses) params.set('statuses', statuses);
  if (sources) params.set('sources', sources);
  if (sales_owners) params.set('sales_owners', sales_owners);

  if (filters.intent) params.set('intent', filters.intent);
  if (filters.vip === true) params.set('vip', '1');
  if (filters.vip === false) params.set('vip', '0');
  if (filters.re_enquiry === true) params.set('re_enquiry', '1');
  if (filters.re_enquiry === false) params.set('re_enquiry', '0');
  if (filters.nudge_pending === true) params.set('nudge', '1');
  if (filters.nudge_pending === false) params.set('nudge', '0');
  if (filters.temperature) params.set('temperature', filters.temperature);
  if (filters.days) params.set('days', String(filters.days));

  if (dateField === 'updated') {
    params.set('date_field', 'updated');
    if (filters.updated_from) params.set('updated_from', filters.updated_from);
    if (filters.updated_to) params.set('updated_to', filters.updated_to);
  } else {
    if (filters.created_from) params.set('created_from', filters.created_from);
    if (filters.created_to) params.set('created_to', filters.created_to);
  }

  if (filters.meta_qualified === true) params.set('meta_qualified', '1');
  if (filters.meta_qualified === false) params.set('meta_qualified', '0');
  if (filters.metric) params.set('metric', filters.metric);
  if (filters.mine) params.set('mine', '1');

  const agent = (agentQuery || '').trim();
  if (agent) params.set('agent', agent);
  return params;
};

export const buildLeadListParams = (filters, search = '') => {
  const params = {};
  const dateField = normalizeDateField(filters.date_field);

  const budgets = encodeCommaList(filters.budgets);
  const locations = encodeCommaList(filters.locations);
  const projects = encodeCommaList(filters.projects);
  const statuses = encodeCommaList(filters.statuses);
  const sources = encodeCommaList(filters.sources);
  const sales_owners = encodeCommaList(filters.sales_owners);

  if (budgets) params.budgets = budgets;
  if (locations) params.locations = locations;
  if (projects) params.projects = projects;
  if (statuses) params.statuses = statuses;
  if (sources) params.sources = sources;
  if (sales_owners) params.sales_owners = sales_owners;

  if (filters.intent) params.intent = filters.intent;
  if (filters.vip !== null && filters.vip !== undefined) params.vip = filters.vip;
  if (filters.re_enquiry !== null && filters.re_enquiry !== undefined) params.re_enquiry = filters.re_enquiry;
  if (filters.nudge_pending !== null && filters.nudge_pending !== undefined) {
    params.nudge_pending = filters.nudge_pending;
  }
  if (filters.temperature) params.temperature = filters.temperature;
  // dormant filter removed (#43)

  if (dateField === 'updated') {
    // Backend `days` is created_at-only; map updated presets to updated_from/to.
    if (filters.updated_from || filters.updated_to) {
      if (filters.updated_from) params.updated_from = filters.updated_from;
      if (filters.updated_to) params.updated_to = filters.updated_to;
    } else if (filters.days) {
      const d = parseInt(filters.days, 10);
      if (Number.isFinite(d) && d > 0) {
        params.updated_from = addIstDays(-d);
        params.updated_to = formatIstYmd();
      }
    }
  } else if (filters.days) {
    const d = parseInt(filters.days, 10);
    if (Number.isFinite(d) && d > 0) params.days = d;
  } else {
    if (filters.created_from) params.created_from = filters.created_from;
    if (filters.created_to) params.created_to = filters.created_to;
  }

  if (filters.meta_qualified === true || filters.meta_qualified === false) {
    params.meta_qualified = filters.meta_qualified;
  }

  if (filters.metric) params.metric = filters.metric;
  if (filters.mine) params.mine = true;
  if (search) params.search = search;

  return params;
};

export const countActiveFilters = (filters, { includeDuplicates = false } = {}) => {
  let count = 0;
  for (const key of MULTI_FILTER_KEYS) {
    if (Array.isArray(filters[key]) && filters[key].length > 0) count += 1;
  }
  if (filters.intent) count += 1;
  if (filters.vip !== null && filters.vip !== undefined) count += 1;
  if (filters.re_enquiry !== null && filters.re_enquiry !== undefined) count += 1;
  if (filters.nudge_pending !== null && filters.nudge_pending !== undefined) count += 1;
  if (filters.temperature) count += 1;
  if (
    filters.days
    || filters.created_from
    || filters.created_to
    || filters.updated_from
    || filters.updated_to
  ) {
    count += 1;
  }
  if (filters.meta_qualified === true || filters.meta_qualified === false) count += 1;
  if (filters.metric) count += 1;
  if (filters.mine) count += 1;
  if (includeDuplicates) count += 1;
  return count;
};

const normalizeFilterSnapshot = (filters = {}) => ({
  budgets: [...(filters.budgets || [])].map(String).sort(),
  locations: [...(filters.locations || [])].map(String).sort(),
  projects: [...(filters.projects || [])].map(String).sort(),
  statuses: [...(filters.statuses || [])].map(String).sort(),
  sources: [...(filters.sources || [])].map(String).sort(),
  sales_owners: [...(filters.sales_owners || [])].map(String).sort(),
  intent: filters.intent || '',
  vip: filters.vip ?? null,
  re_enquiry: filters.re_enquiry ?? null,
  nudge_pending: filters.nudge_pending ?? null,
  temperature: filters.temperature || '',
  days: filters.days || '',
  created_from: filters.created_from || '',
  created_to: filters.created_to || '',
  updated_from: filters.updated_from || '',
  updated_to: filters.updated_to || '',
  date_field: normalizeDateField(filters.date_field),
  meta_qualified: filters.meta_qualified ?? null,
  metric: filters.metric || '',
  dormant: Boolean(filters.dormant),
  mine: Boolean(filters.mine),
  search: (filters.search || '').trim(),
});

export const filtersMatchView = (currentFilters, currentSearch, viewFilters) => {
  const a = normalizeFilterSnapshot({ ...currentFilters, search: currentSearch });
  const b = normalizeFilterSnapshot(viewFilters);
  const keys = Object.keys(a);
  for (const key of keys) {
    const av = a[key];
    const bv = b[key];
    if (Array.isArray(av) && Array.isArray(bv)) {
      if (av.length !== bv.length) return false;
      for (let i = 0; i < av.length; i += 1) {
        if (av[i] !== bv[i]) return false;
      }
      continue;
    }
    if (av !== bv) return false;
  }
  return true;
};

export const formatMultiLabel = (selected, placeholder, { maxVisible = 1 } = {}) => {
  if (!Array.isArray(selected) || selected.length === 0) return placeholder;
  if (selected.length === 1) return selected[0];
  if (selected.length <= maxVisible) return selected.join(', ');
  return `${placeholder} (${selected.length})`;
};

export const snapshotFiltersForView = (filters, search) => ({
  budgets: [...(filters.budgets || [])],
  locations: [...(filters.locations || [])],
  projects: [...(filters.projects || [])],
  statuses: [...(filters.statuses || [])],
  sources: [...(filters.sources || [])],
  sales_owners: [...(filters.sales_owners || [])],
  vip: filters.vip ?? null,
  re_enquiry: filters.re_enquiry ?? null,
  nudge_pending: filters.nudge_pending ?? null,
  intent: filters.intent || '',
  temperature: filters.temperature || '',
  days: filters.days || '',
  created_from: filters.created_from || '',
  created_to: filters.created_to || '',
  updated_from: filters.updated_from || '',
  updated_to: filters.updated_to || '',
  date_field: normalizeDateField(filters.date_field),
  meta_qualified: filters.meta_qualified ?? null,
  metric: filters.metric || '',
  dormant: Boolean(filters.dormant),
  mine: Boolean(filters.mine),
  search: (search || '').trim(),
});

export const applyViewFiltersToState = (viewFilters) => {
  let projects = [...(viewFilters.projects || [])];
  if (projects.length === 0 && viewFilters.project) {
    projects = parseCommaList(viewFilters.project);
  }

  const filters = {
    ...emptyLeadFilters(),
    budgets: [...(viewFilters.budgets || [])],
    locations: [...(viewFilters.locations || [])],
    projects,
    statuses: [...(viewFilters.statuses || [])],
    sources: [...(viewFilters.sources || [])],
    sales_owners: [...(viewFilters.sales_owners || [])],
    intent: viewFilters.intent || '',
    vip: viewFilters.vip ?? null,
    re_enquiry: viewFilters.re_enquiry ?? null,
    nudge_pending: viewFilters.nudge_pending ?? null,
    temperature: viewFilters.temperature || '',
    days: viewFilters.days || '',
    created_from: viewFilters.created_from || '',
    created_to: viewFilters.created_to || '',
    updated_from: viewFilters.updated_from || '',
    updated_to: viewFilters.updated_to || '',
    date_field: normalizeDateField(viewFilters.date_field),
    meta_qualified: viewFilters.meta_qualified ?? null,
    metric: viewFilters.metric || '',
    dormant: Boolean(viewFilters.dormant),
    mine: Boolean(viewFilters.mine),
  };
  const search = (viewFilters.search || '').trim();
  return { filters, search };
};

export const toggleMultiFilterValue = (selected, value) => {
  const list = Array.isArray(selected) ? [...selected] : [];
  const idx = list.indexOf(value);
  if (idx >= 0) {
    list.splice(idx, 1);
  } else {
    list.push(value);
  }
  return list;
};
