import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { Filter, Megaphone } from 'lucide-react';
import { toast } from 'sonner';
import { metaAdsAPI } from '../../services/api';
import { MultiSelectFilterDropdown } from '../leads/MultiSelectFilterDropdown';
import { PRESETS, isValidRange, matchPreset, presetRange } from '../../utils/metaAdsPeriod';
import { MetaSyncStatus } from './MetaSyncStatus';
import { MetaKpiCards } from './MetaKpiCards';
import { MetaTrendChart } from './MetaTrendChart';
import { MetaProjectFunnel } from './MetaProjectFunnel';
import { MetaEntityTable } from './MetaEntityTable';
import { MetaEntityDrawer } from './MetaEntityDrawer';

const DEFAULT_PRESET = '30d';

// Admin-only Meta Ads performance: KPIs vs previous period, daily trend,
// project funnel (Meta spend vs CRM outcomes) and a drill-down table.
export function MetaAdsSection() {
  const initial = useMemo(() => presetRange(DEFAULT_PRESET), []);
  const [range, setRange] = useState({ from: initial.from, to: initial.to });
  const [projects, setProjects] = useState([]);
  const [overview, setOverview] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [lastSync, setLastSync] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [drawerTarget, setDrawerTarget] = useState(null);
  const reqId = useRef(0);

  const validRange = isValidRange(range.from, range.to);
  const projectsKey = projects.join(',');
  const activePreset = matchPreset(range.from, range.to);

  useEffect(() => {
    if (!validRange) return;
    const id = ++reqId.current;
    setLoading(true);
    setError(false);
    const base = { date_from: range.from, date_to: range.to };
    Promise.all([
      metaAdsAPI.getOverview({ ...base, ...(projectsKey ? { projects: projectsKey } : {}) }),
      metaAdsAPI.getProjectFunnel(base),
      metaAdsAPI.getLastSync(),
    ])
      .then(([ov, fn, ls]) => {
        if (id !== reqId.current) return; // a newer request superseded this one
        setOverview(ov.data);
        setFunnel(fn.data);
        setLastSync(ls.data);
      })
      .catch(() => {
        if (id !== reqId.current) return;
        setError(true);
        toast.error('Failed to load Meta Ads data');
      })
      .finally(() => { if (id === reqId.current) setLoading(false); });
  }, [range.from, range.to, projectsKey, validRange, refreshKey]);

  const onSynced = useCallback(() => setRefreshKey((k) => k + 1), []);

  // Options come from the (unfiltered) funnel so the list stays stable while filtering.
  const projectOptions = useMemo(() => (funnel?.rows || []).map((r) => r.project), [funnel]);
  const funnelRows = useMemo(() => {
    if (!funnel || !projects.length) return funnel;
    const rows = funnel.rows.filter((r) => projects.includes(r.project));
    // Totals are for all projects, so they are hidden while filtering.
    return { ...funnel, rows, totals: null };
  }, [funnel, projects]);

  const applyPreset = (key) => {
    const r = presetRange(key);
    if (r) setRange({ from: r.from, to: r.to });
  };

  const empty = overview && overview.current && overview.current.spend === 0 && overview.current.impressions === 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-crm-elevated border border-white/5 rounded-xl p-6 space-y-5"
      data-testid="meta-ads-section"
    >
      <h3 className="text-white font-medium flex items-center gap-2">
        <Megaphone size={18} className="text-[#C5A059]" /> Meta Ads Performance
      </h3>

      <MetaSyncStatus lastSync={lastSync} onLastSync={setLastSync} onSynced={onSynced} />

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-wrap gap-1.5" data-testid="meta-ads-presets">
          {PRESETS.map((p) => (
            <button
              key={p.key}
              type="button"
              onClick={() => applyPreset(p.key)}
              className={`px-2.5 py-1.5 rounded-md text-xs transition-colors ${
                activePreset === p.key ? 'bg-[#C5A059]/20 text-[#C5A059]' : 'bg-white/5 text-crm-fg-muted hover:text-crm-fg-secondary'
              }`}
              data-testid={`meta-preset-${p.key}`}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div>
          <label className="text-crm-fg-secondary text-xs mb-1.5 block">From</label>
          <input
            type="date"
            value={range.from}
            max={range.to}
            onChange={(e) => setRange((r) => ({ ...r, from: e.target.value }))}
            className="bg-crm-muted border border-crm-border rounded-lg px-3 py-1.5 text-white text-sm focus:border-[#C5A059]/50 focus:outline-none"
            data-testid="meta-ads-date-from"
          />
        </div>
        <div>
          <label className="text-crm-fg-secondary text-xs mb-1.5 block">To</label>
          <input
            type="date"
            value={range.to}
            min={range.from}
            onChange={(e) => setRange((r) => ({ ...r, to: e.target.value }))}
            className="bg-crm-muted border border-crm-border rounded-lg px-3 py-1.5 text-white text-sm focus:border-[#C5A059]/50 focus:outline-none"
            data-testid="meta-ads-date-to"
          />
        </div>
        <MultiSelectFilterDropdown
          label="Project"
          icon={Filter}
          options={projectOptions}
          selected={projects}
          onChange={setProjects}
          loading={loading && !funnel}
          testId="meta-ads-project-filter"
        />
      </div>

      {!validRange && (
        <div className="text-amber-400 text-xs" data-testid="meta-ads-range-error">
          Pick a valid range (From on or before To, at most 400 days).
        </div>
      )}

      {validRange && loading && !overview && (
        <div className="text-crm-fg-muted text-sm py-8 text-center" data-testid="meta-ads-loading">Loading Meta Ads data…</div>
      )}

      {validRange && error && (
        <div className="text-red-400 text-sm py-8 text-center" data-testid="meta-ads-load-error">Could not load Meta Ads data.</div>
      )}

      {validRange && overview && !error && (
        <div className={loading ? 'opacity-60 transition-opacity space-y-5' : 'space-y-5'}>
          {empty ? (
            <div className="text-crm-fg-muted text-sm py-8 text-center" data-testid="meta-ads-empty-state">
              No Meta Ads data for this range yet. The daily sync job populates this automatically.
            </div>
          ) : (
            <>
              <MetaKpiCards overview={overview} />
              <MetaTrendChart series={overview.series} />
            </>
          )}
          <MetaProjectFunnel funnel={funnelRows} />
          <MetaEntityTable
            dateFrom={range.from}
            dateTo={range.to}
            projects={projects}
            refreshKey={refreshKey}
            onOpen={setDrawerTarget}
          />
        </div>
      )}

      <MetaEntityDrawer
        target={drawerTarget}
        dateFrom={range.from}
        dateTo={range.to}
        onClose={() => setDrawerTarget(null)}
      />
    </motion.div>
  );
}

export default MetaAdsSection;
