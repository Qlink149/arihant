import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Download, Search } from 'lucide-react';
import { toast } from 'sonner';
import { metaAdsAPI } from '../../services/api';
import {
  downloadCsv, formatCompact, formatINR, formatInt, formatPct, statusGroup, statusLabel, toCsv,
} from '../../utils/metaAdsFormat';

const PAGE = 50;
const NEXT_LEVEL = { campaign: 'adset', adset: 'ad' };
const LEVEL_NOUN = { campaign: 'campaign', adset: 'ad set', ad: 'ad' };

const STATUS_CLASS = {
  active: 'bg-emerald-500/15 text-emerald-400',
  paused: 'bg-zinc-500/20 text-zinc-300',
  unknown: 'bg-white/5 text-crm-fg-muted',
};

const COLUMNS = [
  { key: 'spend', label: 'Spend', fmt: (r) => formatCompact(r.spend, { rupee: true }) },
  { key: 'leads', label: 'Leads', fmt: (r) => formatInt(r.leads) },
  { key: 'cpl', label: 'CPL', fmt: (r) => formatINR(r.cpl) },
  { key: 'impressions', label: 'Impr.', fmt: (r) => formatCompact(r.impressions) },
  { key: 'clicks', label: 'Clicks', fmt: (r) => formatInt(r.clicks) },
  { key: 'ctr', label: 'CTR', fmt: (r) => formatPct(r.ctr) },
  { key: 'cpm', label: 'CPM', fmt: (r) => formatINR(r.cpm) },
];

const CSV_COLUMNS = [
  { label: 'Campaign', value: (r) => r.name },
  { label: 'Campaign ID', value: (r) => r.entity_id },
  { label: 'Status', value: (r) => statusLabel(r.effective_status) },
  { label: 'Objective', value: (r) => r.objective },
  { label: 'Project', value: (r) => r.resolved_project },
  { label: 'Spend', value: (r) => r.spend },
  { label: 'Meta leads', value: (r) => r.leads },
  { label: 'CPL', value: (r) => r.cpl },
  { label: 'Impressions', value: (r) => r.impressions },
  { label: 'Clicks', value: (r) => r.clicks },
  { label: 'CTR %', value: (r) => r.ctr },
  { label: 'CPM', value: (r) => r.cpm },
  { label: 'CRM leads', value: (r) => r.crm_leads },
  { label: 'CRM site visits', value: (r) => r.crm_site_visits },
  { label: 'CRM bookings', value: (r) => r.crm_bookings },
];

function StatusPill({ status }) {
  const g = statusGroup(status);
  return <span className={`px-2 py-0.5 rounded-full text-[11px] ${STATUS_CLASS[g]}`}>{statusLabel(status)}</span>;
}

function EntityRow({ row, level, depth, params, onOpen }) {
  const [open, setOpen] = useState(false);
  const child = NEXT_LEVEL[level];
  const showCrm = level === 'campaign';
  return (
    <>
      <tr className="border-b border-white/5 hover:bg-white/[0.02]" data-testid={`meta-row-${level}-${row.entity_id}`}>
        <td className="py-2 px-3 text-left">
          <div className="flex items-center gap-1.5" style={{ paddingLeft: depth * 18 }}>
            {child ? (
              <button
                type="button"
                onClick={() => setOpen((o) => !o)}
                className="text-crm-fg-muted hover:text-white flex-shrink-0"
                aria-label={open ? 'Collapse' : 'Expand'}
                data-testid={`meta-expand-${level}-${row.entity_id}`}
              >
                {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </button>
            ) : (
              <span className="w-[14px] flex-shrink-0" />
            )}
            <button
              type="button"
              onClick={() => onOpen({ level, entity_id: row.entity_id, name: row.name })}
              className="text-white hover:text-[#C5A059] text-left text-sm truncate max-w-[340px]"
              title={row.name}
              data-testid={`meta-open-${level}-${row.entity_id}`}
            >
              {row.name}
            </button>
          </div>
        </td>
        <td className="py-2 px-3"><StatusPill status={row.effective_status} /></td>
        {COLUMNS.map((c) => (
          <td key={c.key} className="py-2 px-3 text-right text-crm-fg-secondary whitespace-nowrap">{c.fmt(row)}</td>
        ))}
        {showCrm && (
          <td
            className="py-2 px-3 text-right text-crm-fg-secondary"
            title={row.crm_leads == null ? 'No CRM leads carry this campaign ID yet' : undefined}
          >
            {row.crm_leads == null ? '—' : `${row.crm_leads} / ${row.crm_site_visits} / ${row.crm_bookings}`}
          </td>
        )}
      </tr>
      {open && child && (
        <ChildRows level={child} parentId={row.entity_id} depth={depth + 1} params={params} onOpen={onOpen} showCrm={showCrm} />
      )}
    </>
  );
}

function ChildRows({ level, parentId, depth, params, onOpen, showCrm }) {
  const [state, setState] = useState({ loading: true, error: false, rows: [], total: 0 });
  useEffect(() => {
    let cancelled = false;
    setState({ loading: true, error: false, rows: [], total: 0 });
    metaAdsAPI
      .getBreakdown({ ...params, level, parent_id: parentId, limit: 200, sort_by: 'spend', sort_dir: 'desc' })
      .then((res) => { if (!cancelled) setState({ loading: false, error: false, rows: res.data.rows, total: res.data.total }); })
      .catch(() => { if (!cancelled) setState({ loading: false, error: true, rows: [], total: 0 }); });
    return () => { cancelled = true; };
  }, [params, level, parentId]);

  const span = 9 + (showCrm ? 1 : 0);
  if (state.loading) {
    return <tr><td colSpan={span} className="py-2 px-3 text-xs text-crm-fg-muted" style={{ paddingLeft: depth * 18 + 12 }}>Loading {LEVEL_NOUN[level]}s…</td></tr>;
  }
  if (state.error) {
    return <tr><td colSpan={span} className="py-2 px-3 text-xs text-red-400" style={{ paddingLeft: depth * 18 + 12 }}>Could not load {LEVEL_NOUN[level]}s.</td></tr>;
  }
  if (!state.rows.length) {
    return <tr><td colSpan={span} className="py-2 px-3 text-xs text-crm-fg-muted" style={{ paddingLeft: depth * 18 + 12 }}>No {LEVEL_NOUN[level]}s with activity in this range.</td></tr>;
  }
  return (
    <>
      {state.rows.map((r) => (
        <EntityRow key={r.entity_id} row={r} level={level} depth={depth} params={params} onOpen={onOpen} />
      ))}
      {state.total > state.rows.length && (
        <tr><td colSpan={span} className="py-2 px-3 text-xs text-crm-fg-muted" style={{ paddingLeft: depth * 18 + 12 }}>Showing top {state.rows.length} of {state.total} by spend.</td></tr>
      )}
    </>
  );
}

export function MetaEntityTable({ dateFrom, dateTo, projects, refreshKey, onOpen }) {
  const [sort, setSort] = useState({ by: 'spend', dir: 'desc' });
  const [status, setStatus] = useState('all');
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [includeIdle, setIncludeIdle] = useState(false);
  const [state, setState] = useState({ loading: true, error: false, rows: [], total: 0, entityData: true });
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput.trim()), 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const projectsKey = projects.join(',');
  const baseParams = useMemo(
    () => ({
      date_from: dateFrom,
      date_to: dateTo,
      ...(projectsKey ? { projects: projectsKey } : {}),
      ...(includeIdle ? { include_idle: true } : {}),
    }),
    [dateFrom, dateTo, projectsKey, includeIdle],
  );

  // Any change to the query restarts the list from the first page.
  useEffect(() => { setOffset(0); }, [baseParams, sort, status, search, refreshKey]);

  useEffect(() => {
    let cancelled = false;
    const append = offset > 0;
    if (!append) setState((s) => ({ ...s, loading: true, error: false }));
    metaAdsAPI
      .getBreakdown({
        ...baseParams,
        level: 'campaign',
        sort_by: sort.by,
        sort_dir: sort.dir,
        ...(status !== 'all' ? { status } : {}),
        ...(search ? { search } : {}),
        limit: PAGE,
        offset,
      })
      .then((res) => {
        if (cancelled) return;
        setState((s) => ({
          loading: false,
          error: false,
          rows: append ? [...s.rows, ...res.data.rows] : res.data.rows,
          total: res.data.total,
          entityData: res.data.entity_data_available,
        }));
      })
      .catch(() => { if (!cancelled) setState((s) => ({ ...s, loading: false, error: true })); });
    return () => { cancelled = true; };
  }, [baseParams, sort, status, search, offset, refreshKey]);

  const toggleSort = useCallback((key) => {
    setSort((s) => (s.by === key ? { by: key, dir: s.dir === 'desc' ? 'asc' : 'desc' } : { by: key, dir: 'desc' }));
  }, []);

  const exportCsv = () => {
    if (!state.rows.length) { toast.info('Nothing to export'); return; }
    downloadCsv(`meta-ads-campaigns_${dateFrom}_${dateTo}.csv`, toCsv(state.rows, CSV_COLUMNS));
  };

  const sortMark = (key) => (sort.by === key ? (sort.dir === 'desc' ? ' ↓' : ' ↑') : '');
  const childParams = useMemo(() => baseParams, [baseParams]);

  return (
    <div data-testid="meta-entities">
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 mb-3">
        <h4 className="text-white text-sm font-medium">Campaigns → ad sets → ads</h4>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-crm-fg-muted" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search name or ID"
              className="bg-crm-muted border border-crm-border rounded-lg pl-8 pr-3 py-1.5 text-white text-xs w-48 focus:border-[#C5A059]/50 focus:outline-none"
              data-testid="meta-entity-search"
            />
          </div>
          {['all', 'active', 'paused'].map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatus(s)}
              className={`px-2.5 py-1 rounded-md text-xs capitalize transition-colors ${
                status === s ? 'bg-[#C5A059]/20 text-[#C5A059]' : 'bg-white/5 text-crm-fg-muted hover:text-crm-fg-secondary'
              }`}
              data-testid={`meta-status-${s}`}
            >
              {s}
            </button>
          ))}
          <label className="flex items-center gap-1.5 text-xs text-crm-fg-muted cursor-pointer">
            <input
              type="checkbox"
              checked={includeIdle}
              onChange={(e) => setIncludeIdle(e.target.checked)}
              data-testid="meta-include-idle"
            />
            Include no-spend
          </label>
          <button
            type="button"
            onClick={exportCsv}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs bg-white/5 text-crm-fg-secondary hover:text-white"
            data-testid="meta-export-csv"
          >
            <Download size={12} /> Export CSV
          </button>
        </div>
      </div>

      {!state.entityData && !state.loading && (
        <p className="text-amber-400/90 text-xs mb-2" data-testid="meta-entity-status-note">
          Campaign status and objective appear after the next sync (use “Sync now”).
        </p>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-crm-border">
              <th className="text-left text-crm-fg-muted font-medium py-2 px-3 text-xs">
                <button type="button" onClick={() => toggleSort('name')} data-testid="meta-sort-name">Name{sortMark('name')}</button>
              </th>
              <th className="text-left text-crm-fg-muted font-medium py-2 px-3 text-xs">Status</th>
              {COLUMNS.map((c) => (
                <th key={c.key} className="text-right text-crm-fg-muted font-medium py-2 px-3 text-xs whitespace-nowrap">
                  <button type="button" onClick={() => toggleSort(c.key)} data-testid={`meta-sort-${c.key}`}>{c.label}{sortMark(c.key)}</button>
                </th>
              ))}
              <th className="text-right text-crm-fg-muted font-medium py-2 px-3 text-xs whitespace-nowrap" title="CRM leads / site visits / bookings tagged with this campaign ID">CRM l/v/b</th>
            </tr>
          </thead>
          <tbody>
            {state.loading && (
              <tr><td colSpan={10} className="py-8 text-center text-crm-fg-muted text-sm">Loading campaigns…</td></tr>
            )}
            {state.error && !state.loading && (
              <tr><td colSpan={10} className="py-8 text-center text-red-400 text-sm">Could not load campaigns.</td></tr>
            )}
            {!state.loading && !state.error && state.rows.length === 0 && (
              <tr><td colSpan={10} className="py-8 text-center text-crm-fg-muted text-sm" data-testid="meta-entities-empty">No campaigns match these filters.</td></tr>
            )}
            {!state.loading && state.rows.map((r) => (
              <EntityRow key={r.entity_id} row={r} level="campaign" depth={0} params={childParams} onOpen={onOpen} />
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between mt-3 text-xs text-crm-fg-muted">
        <span data-testid="meta-entities-count">Showing {state.rows.length} of {state.total} campaigns</span>
        {state.rows.length < state.total && (
          <button
            type="button"
            onClick={() => setOffset(state.rows.length)}
            className="px-3 py-1 rounded-md bg-white/5 hover:text-white"
            data-testid="meta-load-more"
          >
            Load more
          </button>
        )}
      </div>
    </div>
  );
}

export default MetaEntityTable;
