import React, { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { toast } from 'sonner';
import { CalendarCheck, Building, Users } from 'lucide-react';
import { analyticsAPI, usersAPI } from '../services/api';

const PRESET_OPTIONS = [
  { value: 'week', label: 'This week' },
  { value: 'month', label: 'This month' },
  { value: 'quarter', label: 'This quarter' },
  { value: 'custom', label: 'Custom range' },
];

const todayISO = () => new Date().toISOString().slice(0, 10);

/**
 * #53/#54: Permanent site-visit completion report.
 * Reads the append-only `site_visit_events` log (survives later status changes),
 * grouped by project, filterable by date range/preset + sales owner.
 */
const SiteVisitsPage = () => {
  const [preset, setPreset] = useState('month');
  const [dateFrom, setDateFrom] = useState(todayISO());
  const [dateTo, setDateTo] = useState(todayISO());
  const [salesOwnerId, setSalesOwnerId] = useState('');
  const [assignees, setAssignees] = useState([]);
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    usersAPI
      .listAssignees()
      .then(({ data }) => setAssignees(Array.isArray(data) ? data : []))
      .catch(() => setAssignees([]));
  }, []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const params = {
      sales_owner_id: salesOwnerId || undefined,
      ...(preset === 'custom'
        ? { date_from: dateFrom, date_to: dateTo }
        : { preset }),
    };
    analyticsAPI
      .getSiteVisitReport(params)
      .then(({ data }) => {
        if (!alive) return;
        setReport(data);
      })
      .catch(() => {
        if (!alive) return;
        toast.error('Failed to load site visit report');
        setReport(null);
      })
      .finally(() => {
        if (!alive) return;
        setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [preset, dateFrom, dateTo, salesOwnerId]);

  const byProject = useMemo(() => report?.by_project || [], [report]);
  const total = report?.total ?? 0;
  const maxCount = useMemo(
    () => byProject.reduce((max, row) => Math.max(max, row.count), 0) || 1,
    [byProject]
  );

  return (
    <div className="space-y-4" data-testid="site-visits-page">
      <div>
        <h1 className="text-xl font-semibold text-white tracking-tight" data-testid="site-visits-title">
          Site Visits <span className="text-[#C5A059]">Report</span>
        </h1>
        <p className="text-crm-fg-muted mt-1 text-sm">
          Permanent log of visit completions by project — survives later status changes.
        </p>
      </div>

      {/* Filters */}
      <div className="bg-crm-elevated border border-white/5 rounded-xl p-4 flex flex-wrap items-end gap-3" data-testid="site-visits-filters">
        <div>
          <label className="text-crm-fg-secondary text-xs mb-1.5 block">Period</label>
          <select
            value={preset}
            onChange={(e) => setPreset(e.target.value)}
            className="bg-crm-muted border border-crm-border rounded-lg px-3 py-2 text-white text-sm focus:border-[#C5A059]/50 focus:outline-none"
            data-testid="site-visits-preset"
          >
            {PRESET_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
        {preset === 'custom' && (
          <>
            <div>
              <label className="text-crm-fg-secondary text-xs mb-1.5 block">From</label>
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="bg-crm-muted border border-crm-border rounded-lg px-3 py-2 text-white text-sm focus:border-[#C5A059]/50 focus:outline-none"
                data-testid="site-visits-date-from"
              />
            </div>
            <div>
              <label className="text-crm-fg-secondary text-xs mb-1.5 block">To</label>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="bg-crm-muted border border-crm-border rounded-lg px-3 py-2 text-white text-sm focus:border-[#C5A059]/50 focus:outline-none"
                data-testid="site-visits-date-to"
              />
            </div>
          </>
        )}
        <div>
          <label className="text-crm-fg-secondary text-xs mb-1.5 block">Sales owner</label>
          <select
            value={salesOwnerId}
            onChange={(e) => setSalesOwnerId(e.target.value)}
            className="bg-crm-muted border border-crm-border rounded-lg px-3 py-2 text-white text-sm min-w-[180px] focus:border-[#C5A059]/50 focus:outline-none"
            data-testid="site-visits-owner-select"
          >
            <option value="">All sales owners</option>
            {assignees.map((a) => (
              <option key={a.id || a.user_id} value={a.id || a.user_id}>
                {a.full_name || a.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Total */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-crm-elevated border border-white/5 rounded-xl p-5 flex items-center gap-4"
        data-testid="site-visits-total-card"
      >
        <div className="w-11 h-11 rounded-lg bg-[#C5A059]/10 flex items-center justify-center">
          <CalendarCheck size={22} className="text-[#C5A059]" />
        </div>
        <div>
          <p className="text-white text-2xl font-semibold" data-testid="site-visits-total">{total}</p>
          <p className="text-crm-fg-muted text-xs mt-0.5">Total visits completed</p>
        </div>
      </motion.div>

      {/* By project */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="bg-crm-elevated border border-white/5 rounded-xl p-6"
        data-testid="site-visits-by-project"
      >
        <h3 className="text-white font-medium mb-4 flex items-center gap-2">
          <Building size={18} className="text-[#C5A059]" /> Visits by project
        </h3>

        {loading ? (
          <div className="text-crm-fg-muted text-sm py-8 text-center">Loading…</div>
        ) : byProject.length === 0 ? (
          <div className="text-center py-10" data-testid="site-visits-empty">
            <Users className="mx-auto text-crm-fg-muted" size={36} />
            <p className="text-crm-fg-muted text-sm mt-3">No site visits completed in this period.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {byProject.map((row) => (
              <div key={row.project} className="flex items-center gap-3" data-testid={`site-visits-row-${row.project}`}>
                <span className="text-white text-sm w-40 shrink-0 truncate" title={row.project}>{row.project}</span>
                <div className="flex-1 h-2 rounded-full bg-white/5 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-[#C5A059]"
                    style={{ width: `${Math.max(4, (row.count / maxCount) * 100)}%` }}
                  />
                </div>
                <span className="text-[#C5A059] text-sm font-medium w-10 text-right">{row.count}</span>
              </div>
            ))}
          </div>
        )}
      </motion.div>
    </div>
  );
};

export default SiteVisitsPage;
