import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { toast } from 'sonner';
import { CalendarCheck, Building, Users } from 'lucide-react';
import { analyticsAPI, usersAPI } from '../services/api';
import { istToday } from '../utils/metaAdsPeriod';

const PRESET_OPTIONS = [
  { value: 'week', label: 'This week' },
  { value: 'month', label: 'This month' },
  { value: 'quarter', label: 'This quarter' },
  { value: 'custom', label: 'Custom range' },
];

// IST calendar day (the report's date range is IST); toISOString() is the UTC date,
// which is a day behind between 00:00 and 05:30 IST.
const todayISO = () => istToday();

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
  const navigate = useNavigate();
  // The visits behind the report: null = closed, '' = all projects, else one project bucket
  const [detailProject, setDetailProject] = useState(null);
  const [detail, setDetail] = useState({ loading: false, error: false, data: null });

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

  const rangeParams = useMemo(
    () => ({
      sales_owner_id: salesOwnerId || undefined,
      ...(preset === 'custom' ? { date_from: dateFrom, date_to: dateTo } : { preset }),
    }),
    [preset, dateFrom, dateTo, salesOwnerId]
  );

  useEffect(() => {
    if (detailProject === null) return undefined;
    let alive = true;
    setDetail({ loading: true, error: false, data: null });
    analyticsAPI
      .getSiteVisitLeads({ ...rangeParams, project: detailProject || undefined })
      .then(({ data }) => { if (alive) setDetail({ loading: false, error: false, data }); })
      .catch(() => { if (alive) setDetail({ loading: false, error: true, data: null }); });
    return () => { alive = false; };
  }, [detailProject, rangeParams]);

  const byProject = useMemo(() => report?.by_project || [], [report]);
  const total = report?.total ?? 0;
  const maxCount = useMemo(
    () => byProject.reduce((max, row) => Math.max(max, row.count), 0) || 1,
    [byProject]
  );

  return (
    <div className="space-y-4" data-testid="site-visits-page">
      <div>
        <h1 className="text-xl font-semibold text-crm-fg tracking-tight" data-testid="site-visits-title">
          Site Visits <span className="text-[#C5A059]">Report</span>
        </h1>
        <p className="text-crm-fg-muted mt-1 text-sm">
          Counts each time a lead moves to <span className="text-crm-fg-secondary">Visit Completed</span>
          {' '}— not call tasks or site-visit notes. Log survives later status changes.
        </p>
      </div>

      {/* Filters */}
      <div className="bg-crm-elevated border border-crm-border rounded-xl p-4 flex flex-wrap items-end gap-3" data-testid="site-visits-filters">
        <div>
          <label className="text-crm-fg-secondary text-xs mb-1.5 block">Period</label>
          <select
            value={preset}
            onChange={(e) => setPreset(e.target.value)}
            className="bg-crm-muted border border-crm-border rounded-lg px-3 py-2 text-crm-fg text-sm focus:border-[#C5A059]/50 focus:outline-none"
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
                className="bg-crm-muted border border-crm-border rounded-lg px-3 py-2 text-crm-fg text-sm focus:border-[#C5A059]/50 focus:outline-none"
                data-testid="site-visits-date-from"
              />
            </div>
            <div>
              <label className="text-crm-fg-secondary text-xs mb-1.5 block">To</label>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="bg-crm-muted border border-crm-border rounded-lg px-3 py-2 text-crm-fg text-sm focus:border-[#C5A059]/50 focus:outline-none"
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
            className="bg-crm-muted border border-crm-border rounded-lg px-3 py-2 text-crm-fg text-sm min-w-[180px] focus:border-[#C5A059]/50 focus:outline-none"
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
        className="bg-crm-elevated border border-crm-border rounded-xl p-5 flex items-center gap-4"
        data-testid="site-visits-total-card"
      >
        <div className="w-11 h-11 rounded-lg bg-[#C5A059]/10 flex items-center justify-center">
          <CalendarCheck size={22} className="text-[#C5A059]" />
        </div>
        <div>
          <p className="text-crm-fg text-2xl font-semibold" data-testid="site-visits-total">{total}</p>
          <p className="text-crm-fg-muted text-xs mt-0.5">Total visits completed</p>
        </div>
      </motion.div>

      {/* By project */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="bg-crm-elevated border border-crm-border rounded-xl p-6"
        data-testid="site-visits-by-project"
      >
        <h3 className="text-crm-fg font-medium mb-4 flex items-center gap-2">
          <Building size={18} className="text-[#C5A059]" /> Visits by project
        </h3>

        {loading ? (
          <div className="text-crm-fg-muted text-sm py-8 text-center">Loading…</div>
        ) : byProject.length === 0 ? (
          <div className="text-center py-10" data-testid="site-visits-empty">
            <Users className="mx-auto text-crm-fg-muted" size={36} />
            <p className="text-crm-fg-muted text-sm mt-3">No Visit Completed transitions in this period.</p>
            <p className="text-crm-fg-muted text-xs mt-1.5 max-w-md mx-auto">
              Completing a “Call For Site Visit” task or adding a site-visit note does not count here —
              only status → Visit Completed.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {byProject.map((row) => (
              <div
                key={row.project}
                className="flex items-center gap-3 cursor-pointer hover:bg-white/[0.03] rounded"
                data-testid={`site-visits-row-${row.project}`}
                onClick={() => setDetailProject(row.project)}
                title="Click to see the leads"
              >
                <span className="text-crm-fg text-sm w-40 shrink-0 truncate" title={row.project}>{row.project}</span>
                <div className="flex-1 h-2 rounded-full bg-crm-muted overflow-hidden">
                  <div
                    className="h-full rounded-full bg-[#C5A059]"
                    style={{ width: `${Math.max(4, (row.count / maxCount) * 100)}%` }}
                  />
                </div>
                <span className="text-[#C5A059] text-sm font-medium w-10 text-right">{row.count}</span>
              </div>
            ))}
            <p className="text-crm-fg-muted text-xs pt-1">Click a project (or View all leads) to see each lead and its current status.</p>
            {byProject.some((r) => r.project === 'Multiple projects') && (
              <p className="text-crm-fg-muted text-xs pt-1" data-testid="site-visits-multi-note">
                “Multiple projects” counts visits by leads interested in more than one project — we can’t tell which
                project was visited, so they are kept together rather than split.
              </p>
            )}
          </div>
        )}
      </motion.div>

      {/* Leads behind the numbers */}
      <div className="bg-crm-elevated border border-crm-border rounded-xl p-6" data-testid="site-visits-detail">
        <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
          <h3 className="text-crm-fg font-medium">
            {detailProject === null ? 'Leads behind this report' : `Leads - ${detailProject || 'all projects'}`}
          </h3>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setDetailProject('')}
              className="px-3 py-1.5 rounded-lg text-xs bg-[#C5A059]/15 text-[#C5A059] hover:bg-[#C5A059]/25"
              data-testid="site-visits-view-all"
            >
              View all leads ({total})
            </button>
            {detailProject !== null && (
              <button type="button" onClick={() => setDetailProject(null)} className="px-3 py-1.5 rounded-lg text-xs bg-white/5 text-crm-fg-muted hover:text-crm-fg" data-testid="site-visits-detail-close">
                Close
              </button>
            )}
          </div>
        </div>
        {detailProject === null ? (
          <p className="text-crm-fg-muted text-sm">Open the list to cross-check each visit and the current status of the lead.</p>
        ) : detail.error ? (
          <div className="text-red-400 text-sm py-6 text-center">Could not load the leads.</div>
        ) : detail.loading || !detail.data ? (
          // !detail.data covers the first render after opening, before the fetch effect has run
          <div className="text-crm-fg-muted text-sm py-6 text-center">Loading...</div>
        ) : (
          <>
            <p className="text-crm-fg-muted text-xs mb-2" data-testid="site-visits-detail-count">
              {detail.data.total} visit{detail.data.total === 1 ? '' : 's'} by {detail.data.distinct_leads} lead{detail.data.distinct_leads === 1 ? '' : 's'}
              {detail.data.total > detail.data.visits.length ? ` (showing the latest ${detail.data.visits.length})` : ''}.
              A lead that completed a visit twice counts twice, as in the report above.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm" data-testid="site-visits-detail-table">
                <thead>
                  <tr className="border-b border-crm-border text-crm-fg-muted text-xs">
                    {['Visit completed (IST)', 'Lead', 'Phone', 'Project', 'Current status', 'Sales owner'].map((h) => (
                      <th key={h} className="text-left font-medium py-2 px-2 whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {detail.data.visits.map((v) => (
                    <tr key={v.event_id} className="border-b border-white/5 hover:bg-white/[0.03]" data-testid={`site-visits-lead-${v.lead_id}`}>
                      <td className="py-2 px-2 text-crm-fg-secondary whitespace-nowrap">
                        {v.visit_completed_at
                          ? new Date(v.visit_completed_at).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
                          : '-'}
                      </td>
                      <td className="py-2 px-2">
                        <button type="button" onClick={() => navigate(`/lead/${v.lead_id}`)} className="text-crm-fg hover:text-[#C5A059] text-left">
                          {v.lead_name}
                        </button>
                      </td>
                      <td className="py-2 px-2 text-crm-fg-secondary">{v.phone || '-'}</td>
                      <td className="py-2 px-2 text-crm-fg-secondary">{v.project}</td>
                      <td className="py-2 px-2" data-testid={`site-visits-status-${v.lead_id}`}>
                        <span className="px-2 py-0.5 rounded-full text-xs bg-white/5 text-crm-fg">{v.current_status || 'Lead removed'}</span>
                      </td>
                      <td className="py-2 px-2 text-crm-fg-secondary">{v.sales_owner || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default SiteVisitsPage;
