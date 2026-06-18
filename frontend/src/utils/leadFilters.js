/**
 * Virtual Customer lead filter state, URL sync, and API param helpers.
 */

const MULTI_FILTER_KEYS = ['budgets', 'locations', 'projects', 'statuses', 'sources'];

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

export const emptyLeadFilters = () => ({
  budgets: [],
  locations: [],
  projects: [],
  statuses: [],
  sources: [],
  intent: '',
  vip: null,
  temperature: '',
  days: '',
  created_from: '',
  created_to: '',
  meta_qualified: null,
  metric: '',
  dormant: false,
});

/** Migrate legacy single-value URL params to array fields. */
export const filtersFromSearchParams = (searchParams) => {
  const base = emptyLeadFilters();

  const budgets = parseCommaList(searchParams.get('budgets') || searchParams.get('budget'));
  const locations = parseCommaList(searchParams.get('locations') || searchParams.get('location'));
  const projects = parseCommaList(searchParams.get('projects') || searchParams.get('project'));
  const statuses = parseCommaList(searchParams.get('statuses') || searchParams.get('status'));
  const sources = parseCommaList(searchParams.get('sources') || searchParams.get('source'));

  const vipRaw = searchParams.get('vip');
  let vip = null;
  if (vipRaw === '1' || vipRaw === 'true') vip = true;
  if (vipRaw === '0' || vipRaw === 'false') vip = false;

  return {
    ...base,
    budgets,
    locations,
    projects,
    statuses,
    sources,
    intent: searchParams.get('intent') || '',
    vip,
    temperature: searchParams.get('temperature') || '',
    days: searchParams.get('days') || '',
    created_from: searchParams.get('created_from') || '',
    created_to: searchParams.get('created_to') || '',
    meta_qualified: parseMetaQualified(searchParams.get('meta_qualified')),
    metric: searchParams.get('metric') || '',
    dormant: searchParams.get('dormant') === '1' || searchParams.get('dormant') === 'true',
  };
};

export const filtersToSearchParams = (filters, agentQuery) => {
  const params = new URLSearchParams();

  const budgets = encodeCommaList(filters.budgets);
  const locations = encodeCommaList(filters.locations);
  const projects = encodeCommaList(filters.projects);
  const statuses = encodeCommaList(filters.statuses);
  const sources = encodeCommaList(filters.sources);

  if (budgets) params.set('budgets', budgets);
  if (locations) params.set('locations', locations);
  if (projects) params.set('projects', projects);
  if (statuses) params.set('statuses', statuses);
  if (sources) params.set('sources', sources);

  if (filters.intent) params.set('intent', filters.intent);
  if (filters.vip === true) params.set('vip', '1');
  if (filters.vip === false) params.set('vip', '0');
  if (filters.temperature) params.set('temperature', filters.temperature);
  if (filters.days) params.set('days', String(filters.days));
  if (filters.created_from) params.set('created_from', filters.created_from);
  if (filters.created_to) params.set('created_to', filters.created_to);
  if (filters.meta_qualified === true) params.set('meta_qualified', '1');
  if (filters.meta_qualified === false) params.set('meta_qualified', '0');
  if (filters.metric) params.set('metric', filters.metric);
  if (filters.dormant) params.set('dormant', '1');

  const agent = (agentQuery || '').trim();
  if (agent) params.set('agent', agent);
  return params;
};

export const buildLeadListParams = (filters, search = '') => {
  const params = {};

  const budgets = encodeCommaList(filters.budgets);
  const locations = encodeCommaList(filters.locations);
  const projects = encodeCommaList(filters.projects);
  const statuses = encodeCommaList(filters.statuses);
  const sources = encodeCommaList(filters.sources);

  if (budgets) params.budgets = budgets;
  if (locations) params.locations = locations;
  if (projects) params.projects = projects;
  if (statuses) params.statuses = statuses;
  if (sources) params.sources = sources;

  if (filters.intent) params.intent = filters.intent;
  if (filters.vip !== null && filters.vip !== undefined) params.vip = filters.vip;
  if (filters.temperature) params.temperature = filters.temperature;
  if (filters.dormant) params.dormant = true;

  if (filters.days) {
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
  if (filters.temperature) count += 1;
  if (filters.days || filters.created_from || filters.created_to) count += 1;
  if (filters.meta_qualified === true || filters.meta_qualified === false) count += 1;
  if (filters.metric) count += 1;
  if (filters.dormant) count += 1;
  if (includeDuplicates) count += 1;
  return count;
};

const normalizeFilterSnapshot = (filters = {}) => ({
  budgets: [...(filters.budgets || [])].map(String).sort(),
  locations: [...(filters.locations || [])].map(String).sort(),
  projects: [...(filters.projects || [])].map(String).sort(),
  statuses: [...(filters.statuses || [])].map(String).sort(),
  sources: [...(filters.sources || [])].map(String).sort(),
  intent: filters.intent || '',
  vip: filters.vip ?? null,
  temperature: filters.temperature || '',
  days: filters.days || '',
  created_from: filters.created_from || '',
  created_to: filters.created_to || '',
  meta_qualified: filters.meta_qualified ?? null,
  metric: filters.metric || '',
  dormant: Boolean(filters.dormant),
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
  vip: filters.vip ?? null,
  intent: filters.intent || '',
  temperature: filters.temperature || '',
  days: filters.days || '',
  created_from: filters.created_from || '',
  created_to: filters.created_to || '',
  meta_qualified: filters.meta_qualified ?? null,
  metric: filters.metric || '',
  dormant: Boolean(filters.dormant),
  search: (search || '').trim(),
});

export const applyViewFiltersToState = (viewFilters) => {
  const filters = {
    ...emptyLeadFilters(),
    budgets: [...(viewFilters.budgets || [])],
    locations: [...(viewFilters.locations || [])],
    projects: [...(viewFilters.projects || [])],
    statuses: [...(viewFilters.statuses || [])],
    sources: [...(viewFilters.sources || [])],
    intent: viewFilters.intent || '',
    vip: viewFilters.vip ?? null,
    temperature: viewFilters.temperature || '',
    days: viewFilters.days || '',
    created_from: viewFilters.created_from || '',
    created_to: viewFilters.created_to || '',
    meta_qualified: viewFilters.meta_qualified ?? null,
    metric: viewFilters.metric || '',
    dormant: Boolean(viewFilters.dormant),
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
