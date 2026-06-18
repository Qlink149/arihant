import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { motion, AnimatePresence } from 'framer-motion';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { analyticsAPI } from '../services/api';
import { toast } from 'sonner';
import { SalesDrilldownLeadRow } from '../components/dashboard/SalesDrilldownLeadRow';
import {
  shouldUseVirtualList,
  VIRTUAL_CARD_ESTIMATE_PX,
} from '../constants/performanceFlags';
import { useInfiniteScrollNearBottom } from '../hooks/useInfiniteScrollNearBottom';
import {
  Users, TrendingUp, TrendingDown, Award,
  Flame, Sun,
  ChevronUp, ChevronDown, ArrowUpDown, X, Eye, MapPin,
  CheckCircle, PhoneOff, Briefcase
} from 'lucide-react';
import { formatDateIST } from '../utils/datetime';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell, Legend
} from 'recharts';
import { Button } from '../components/ui/button';
import { CrmBadge } from '../components/ui/CrmBadge';
import { SalesPeriodFilters } from '../components/dashboard/SalesPeriodFilters';
import {
  buildSalesDashboardParams,
  emptyDatePeriod,
  getSalesPeriodLabel,
} from '../utils/salesPeriodFilter';
import { useStatsAutoRefresh } from '../hooks/useStatsAutoRefresh';

const STATS_REFRESH_MS = 60_000;

function SalesBarTooltip({ active, payload, label }) {
  if (active && payload?.length) {
    return (
      <div className="bg-[#1A1A1A] border border-white/10 rounded-lg p-3 shadow-xl">
        <p className="text-[#C5A059] font-medium mb-1">{label}</p>
        {payload.map((e, i) => <p key={i} className="text-white text-sm">{e.name}: {e.value}</p>)}
      </div>
    );
  }
  return null;
}

function SalesSortIcon({ field, sortField, sortDir }) {
  if (sortField !== field) return <ArrowUpDown size={12} className="text-[#52525B]" />;
  return sortDir === 'desc' ? <ChevronDown size={12} className="text-[#C5A059]" /> : <ChevronUp size={12} className="text-[#C5A059]" />;
}

const PERSON_COLORS = ['#C5A059', '#3B82F6', '#10B981', '#F59E0B', '#8B5CF6', '#EC4899', '#14B8A6', '#EF4444'];
const NURTURE_COLORS = { Hot: '#EF4444', Warm: '#F59E0B' };

const REP_LEADS_PAGE = 150;

const emptyTotals = () => ({
  total: 0, hot: 0, warm: 0, negotiation: 0, rnr: 0, site_visits: 0, deals_won: 0, deals_lost: 0, deals_closed: 0
});

const SalesDashboardPage = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sortField, setSortField] = useState('deals_won');
  const [sortDir, setSortDir] = useState('desc');
  const [selectedPerson, setSelectedPerson] = useState(null);
  const [repLeads, setRepLeads] = useState([]);
  const [repLeadsTotal, setRepLeadsTotal] = useState(0);
  const [repLeadsLoading, setRepLeadsLoading] = useState(false);
  const [overviewQuarter, setOverviewQuarter] = useState('all');
  const [overviewDatePeriod, setOverviewDatePeriod] = useState(emptyDatePeriod);
  const [periodLabel, setPeriodLabel] = useState('All Time');
  const [rankingData, setRankingData] = useState([]);
  const [rankingLoading, setRankingLoading] = useState(false);
  const prefetchedRef = useRef(new Set());
  const listScrollRef = useRef(null);
  const repFetchBusy = useRef(false);

  const periodParams = useMemo(
    () => buildSalesDashboardParams({ quarter: overviewQuarter, datePeriod: overviewDatePeriod }),
    [overviewQuarter, overviewDatePeriod]
  );

  const fetchData = useCallback(async ({ silent = false } = {}) => {
    try {
      const response = await analyticsAPI.getSalesDashboard(periodParams);
      setDashboard(response.data);
      setPeriodLabel(response.data?.period_label || getSalesPeriodLabel({
        quarter: overviewQuarter,
        datePeriod: overviewDatePeriod,
      }));
    } catch (error) {
      if (!silent) toast.error('Failed to load sales data');
    } finally {
      if (!silent) setLoading(false);
    }
  }, [periodParams, overviewQuarter, overviewDatePeriod]);

  useEffect(() => { fetchData(); }, [fetchData]);

  useStatsAutoRefresh(() => {
    if (dashboard) fetchData({ silent: true });
  }, { intervalMs: STATS_REFRESH_MS, enabled: Boolean(dashboard) });

  useEffect(() => {
    let cancelled = false;
    const loadRanking = async () => {
      setRankingLoading(true);
      try {
        const { data } = await analyticsAPI.getSalesRanking(periodParams);
        if (!cancelled) {
          setRankingData(data.managers ?? []);
          setPeriodLabel((prev) => data.period_label || prev);
        }
      } catch {
        if (!cancelled) toast.error('Failed to load performance ranking');
      } finally {
        if (!cancelled) setRankingLoading(false);
      }
    };
    loadRanking();
    return () => { cancelled = true; };
  }, [periodParams]);

  const salesData = useMemo(() => dashboard?.managers ?? [], [dashboard]);

  const loadRepLeadsPage = useCallback(async (name, skip, { append } = { append: false }) => {
    if (repFetchBusy.current) return;
    repFetchBusy.current = true;
    setRepLeadsLoading(true);
    try {
      const { data } = await analyticsAPI.getSalesRepLeads(name, { skip, limit: REP_LEADS_PAGE, ...periodParams });
      setRepLeadsTotal(data.total ?? 0);
      const batch = data.leads || [];
      setRepLeads((prev) => {
        if (!append) return [...batch];
        const seen = new Set(prev.map((l) => l.id));
        const merged = [...prev];
        for (const row of batch) {
          if (!seen.has(row.id)) {
            seen.add(row.id);
            merged.push(row);
          }
        }
        return merged;
      });
    } catch (e) {
      toast.error('Failed to load rep leads');
    } finally {
      setRepLeadsLoading(false);
      repFetchBusy.current = false;
    }
  }, [periodParams]);

  const prefetchNextRepPage = useCallback((name, nextSkip) => {
    const key = `${name}:${nextSkip}`;
    if (prefetchedRef.current.has(key) || nextSkip >= repLeadsTotal) return;
    prefetchedRef.current.add(key);
    analyticsAPI.getSalesRepLeads(name, { skip: nextSkip, limit: REP_LEADS_PAGE, ...periodParams }).then(({ data }) => {
      const batch = data.leads || [];
      if (!batch.length) return;
      setRepLeads((prev) => {
        const existing = new Set(prev.map((l) => l.id));
        const merged = [...prev];
        for (const row of batch) {
          if (!existing.has(row.id)) merged.push(row);
        }
        return merged;
      });
    }).catch(() => { prefetchedRef.current.delete(key); });
  }, [repLeadsTotal, periodParams]);

  const openRepModal = useCallback((person) => {
    repFetchBusy.current = false;
    prefetchedRef.current = new Set();
    setSelectedPerson(person);
    setRepLeads([]);
    setRepLeadsTotal(person.total ?? 0);
    if (listScrollRef.current) listScrollRef.current.scrollTop = 0;
    loadRepLeadsPage(person.name, 0, { append: false });
  }, [loadRepLeadsPage]);

  const closeRepModal = useCallback(() => {
    setSelectedPerson(null);
    setRepLeads([]);
    setRepLeadsTotal(0);
    prefetchedRef.current = new Set();
    if (searchParams.get('agent')) {
      const next = new URLSearchParams(searchParams);
      next.delete('agent');
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  useEffect(() => {
    if (loading || !dashboard?.managers?.length) return;
    const raw = searchParams.get('agent');
    if (!raw) return;
    const decoded = decodeURIComponent(raw).trim();
    if (!decoded) return;
    const match = dashboard.managers.find(
      (m) => m.name.toLowerCase() === decoded.toLowerCase()
    );
    if (match && (!selectedPerson || selectedPerson.name !== match.name)) {
      openRepModal(match);
    }
  }, [loading, dashboard, searchParams, selectedPerson, openRepModal]);

  useEffect(() => {
    if (!selectedPerson?.name) return;
    if (repLeads.length >= REP_LEADS_PAGE && repLeadsTotal > repLeads.length) {
      prefetchNextRepPage(selectedPerson.name, REP_LEADS_PAGE);
    }
  }, [selectedPerson, repLeads.length, repLeadsTotal, prefetchNextRepPage]);

  const sortedData = useMemo(() => {
    return [...salesData].sort((a, b) => {
      const av = a[sortField], bv = b[sortField];
      if (typeof av === 'number') return sortDir === 'desc' ? bv - av : av - bv;
      return sortDir === 'desc' ? String(bv).localeCompare(String(av)) : String(av).localeCompare(String(bv));
    });
  }, [salesData, sortField, sortDir]);

  const totalStats = useMemo(() => {
    if (dashboard?.totals) return dashboard.totals;
    return emptyTotals();
  }, [dashboard]);

  const handleSort = (field) => {
    if (sortField === field) setSortDir(d => d === 'desc' ? 'asc' : 'desc');
    else { setSortField(field); setSortDir('desc'); }
  };

  const comparisonData = useMemo(() => {
    return salesData.filter(s => s.name !== 'Unassigned').map(s => ({
      name: s.name.split(' ')[0],
      'Assigned': s.total,
      'In Site Visit Stage': s.site_visits,
      'Deals Won': s.deals_won ?? 0,
      'Deals Lost': s.deals_lost ?? 0,
    }));
  }, [salesData]);

  const nurtureDistribution = useMemo(() => {
    return [
      { name: 'Nurturing (Hot)', value: totalStats.hot, color: NURTURE_COLORS.Hot },
      { name: 'Nurturing (Warm)', value: totalStats.warm, color: NURTURE_COLORS.Warm },
    ].filter(d => d.value > 0);
  }, [totalStats]);

  const formatDate = (d) => {
    if (!d) return 'N/A';
    return formatDateIST(d) || 'N/A';
  };

  const handleRepListNearBottom = useCallback(() => {
    if (!selectedPerson || repLeadsLoading) return;
    if (repLeads.length >= repLeadsTotal) return;
    loadRepLeadsPage(selectedPerson.name, repLeads.length, { append: true });
  }, [selectedPerson, repLeadsLoading, repLeads.length, repLeadsTotal, loadRepLeadsPage]);

  const onLeadListScroll = useInfiniteScrollNearBottom(listScrollRef, handleRepListNearBottom);

  const sortedRepLeads = useMemo(
    () => [...repLeads].sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || ''))),
    [repLeads]
  );

  const repLeadRows = useMemo(
    () => sortedRepLeads.map((lead) => ({
      lead,
      formattedDate: formatDate(lead.updated_at || lead.created_at),
    })),
    [sortedRepLeads]
  );

  const useVirtualRepLeads = shouldUseVirtualList(repLeadRows.length);

  const repListVirtualizer = useVirtualizer({
    count: repLeadRows.length,
    getScrollElement: () => listScrollRef.current,
    estimateSize: () => VIRTUAL_CARD_ESTIMATE_PX,
    overscan: 8,
    enabled: useVirtualRepLeads,
    gap: 8,
  });

  const handleDrilldownLeadSelect = useCallback((leadId) => {
    closeRepModal();
    navigate(`/lead/${leadId}`);
  }, [closeRepModal, navigate]);

  if (loading) return (
    <div className="space-y-3 max-w-6xl mx-auto p-2">
      <div className="h-10 w-64 rounded bg-white/5 animate-pulse" />
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
        {[1, 2, 3, 4, 5, 6, 7, 8].map((i) => <div key={i} className="h-20 rounded-lg bg-white/5 animate-pulse" />)}
      </div>
      <div className="h-48 rounded-lg bg-white/5 animate-pulse" />
    </div>
  );

  return (
    <div className="space-y-3">
      <motion.div initial={{ opacity: 0, y: -20 }} animate={{ opacity: 1, y: 0 }}>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-xl font-semibold text-white" data-testid="sales-dashboard-title">Sales Team Dashboard</h1>
            <p className="text-[#A1A1AA] mt-1 text-sm">
              Performance analytics and lead distribution across {salesData.filter(s => s.name !== 'Unassigned').length} team members
              {periodLabel ? ` · ${periodLabel}` : ''}
            </p>
          </div>
          <SalesPeriodFilters
            quarter={overviewQuarter}
            onQuarterChange={setOverviewQuarter}
            datePeriod={overviewDatePeriod}
            onDatePeriodChange={setOverviewDatePeriod}
          />
        </div>
      </motion.div>

      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}
        className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
        {[
          { label: 'Total Leads', value: totalStats.total, icon: Users, color: 'text-[#C5A059]' },
          { label: 'Nurturing Hot', value: totalStats.hot, icon: Flame, color: 'text-red-500' },
          { label: 'Nurturing Warm', value: totalStats.warm, icon: Sun, color: 'text-orange-500' },
          { label: 'In Negotiation', value: totalStats.negotiation, icon: Briefcase, color: 'text-purple-400', testId: 'stat-in-negotiation' },
          { label: 'RNR', value: totalStats.rnr, icon: PhoneOff, color: 'text-yellow-500', testId: 'stat-rnr' },
          { label: 'In Site Visit Stage', value: totalStats.site_visits, icon: MapPin, color: 'text-teal-500', testId: 'stat-site-visits' },
          { label: 'Deals Won', value: totalStats.deals_won ?? 0, icon: CheckCircle, color: 'text-green-500', testId: 'stat-deals-won' },
          { label: 'Deals Lost', value: totalStats.deals_lost ?? 0, icon: TrendingDown, color: 'text-red-400', testId: 'stat-deals-lost' },
        ].map(s => (
          <div key={s.label} className="glass-card rounded-lg p-3 text-center" data-testid={s.testId || `stat-${s.label.toLowerCase().replace(/\s/g, '-')}`}>
            <s.icon className={`mx-auto ${s.color}`} size={20} />
            <p className="text-[#52525B] text-[10px] uppercase mt-1">{s.label}</p>
            <p className={`font-serif text-xl ${s.color}`}>{s.value}</p>
          </div>
        ))}
      </motion.div>

      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }} className="glass-card rounded-lg p-4">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
          <div>
            <h3 className="font-serif text-xl text-white" data-testid="team-overview-title">Sales Team Overview</h3>
            <p className="text-[#52525B] text-xs mt-1">Leads created in {periodLabel}</p>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full" data-testid="sales-team-table">
            <thead>
              <tr className="border-b border-white/10">
                {[
                  { key: 'rank', label: '#' },
                  { key: 'name', label: 'Sales Person' },
                  { key: 'total', label: 'Total' },
                  { key: 'hot', label: 'Nurture Hot', icon: <Flame size={11} className="text-red-500" /> },
                  { key: 'warm', label: 'Nurture Warm', icon: <Sun size={11} className="text-orange-500" /> },
                  { key: 'negotiation', label: 'Negotiation', icon: <Briefcase size={11} className="text-purple-400" /> },
                  { key: 'rnr', label: 'RNR', icon: <PhoneOff size={11} className="text-yellow-500" /> },
                  { key: 'site_visits', label: 'Site Visit Stage' },
                  { key: 'deals_won', label: 'Deals Won' },
                  { key: 'deals_lost', label: 'Deals Lost' },
                  { key: 'conversion_rate', label: 'Conv %' },
                ].map(col => (
                  <th key={col.key} onClick={() => col.key !== 'rank' && handleSort(col.key)}
                    className={`py-3 px-3 text-[#52525B] text-[10px] uppercase tracking-wider ${col.key === 'name' ? 'text-left' : 'text-center'} ${col.key !== 'rank' ? 'cursor-pointer hover:text-[#C5A059]' : ''}`}>
                    <span className={`flex items-center gap-1 ${col.key === 'name' ? 'justify-start' : 'justify-center'}`}>
                      {col.icon} {col.label} {col.key !== 'rank' && (
                        <SalesSortIcon field={col.key} sortField={sortField} sortDir={sortDir} />
                      )}
                    </span>
                  </th>
                ))}
                <th className="py-3 px-3 text-center text-[#52525B] text-[10px] uppercase">Actions</th>
              </tr>
            </thead>
            <tbody>
              {sortedData.map((s, idx) => (
                <tr key={s.name} className={`border-b border-white/5 hover:bg-white/5 transition-colors ${idx === 0 && sortField === 'deals_won' ? 'bg-[#C5A059]/5' : ''}`}
                  data-testid={`sales-row-${s.name}`}>
                  <td className="py-3 px-3 text-center">
                    {idx < 3 ? <Award size={16} className={idx === 0 ? 'text-[#C5A059] mx-auto' : idx === 1 ? 'text-gray-400 mx-auto' : 'text-orange-700 mx-auto'} /> : <span className="text-[#52525B] text-sm">{idx + 1}</span>}
                  </td>
                  <td className="py-3 px-3">
                    <div className="flex items-center gap-2">
                      <div className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-medium" style={{ backgroundColor: `${PERSON_COLORS[idx % PERSON_COLORS.length]}20`, color: PERSON_COLORS[idx % PERSON_COLORS.length] }}>{s.name.charAt(0)}</div>
                      <span className={`text-sm font-medium ${idx === 0 && sortField === 'deals_won' ? 'text-[#C5A059]' : 'text-white'}`}>{s.name}</span>
                    </div>
                  </td>
                  <td className="py-3 px-3 text-center text-white font-medium text-sm">{s.total}</td>
                  <td className="py-3 px-3 text-center text-red-500 text-sm">{s.hot}</td>
                  <td className="py-3 px-3 text-center text-orange-500 text-sm">{s.warm}</td>
                  <td className="py-3 px-3 text-center text-purple-400 text-sm">{s.negotiation ?? 0}</td>
                  <td className="py-3 px-3 text-center text-yellow-500 text-sm">{s.rnr}</td>
                  <td className="py-3 px-3 text-center text-teal-400 text-sm">{s.site_visits}</td>
                  <td className="py-3 px-3 text-center">
                    <CrmBadge variant="success">{s.deals_won ?? 0}</CrmBadge>
                  </td>
                  <td className="py-3 px-3 text-center">
                    <CrmBadge variant="danger">{s.deals_lost ?? 0}</CrmBadge>
                  </td>
                  <td className="py-3 px-3 text-center text-[#A1A1AA] text-sm">{s.conversion_rate ?? 0}%</td>
                  <td className="py-3 px-3 text-center">
                    <Button size="sm" variant="ghost" onClick={() => {
                      const next = new URLSearchParams(searchParams);
                      next.set('agent', s.name);
                      setSearchParams(next, { replace: true });
                      openRepModal(s);
                    }} className="text-[#C5A059] hover:bg-[#C5A059]/10 h-7 px-2" data-testid={`view-${s.name}`}>
                      <Eye size={14} />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </motion.div>

      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }} className="glass-card rounded-lg p-4">
        <div className="mb-6">
          <h3 className="font-serif text-xl text-white">Performance Ranking</h3>
          <p className="text-[#A1A1AA] text-xs mt-1">
            Ranked by conversion rate · leads created in {periodLabel}
          </p>
        </div>
        <div className="space-y-3">
          {rankingLoading ? (
            Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="flex items-center gap-4 animate-pulse">
                <div className="w-8 h-5 bg-white/5 rounded" />
                <div className="w-7 h-7 rounded-full bg-white/5" />
                <div className="w-32 h-4 bg-white/5 rounded" />
                <div className="flex-1 h-6 bg-white/5 rounded-full" />
              </div>
            ))
          ) : rankingData.length === 0 ? (
            <p className="text-[#A1A1AA] text-sm text-center py-6">No leads in this period</p>
          ) : (
            rankingData.map((s, idx) => {
            const maxTotal = Math.max(...rankingData.map(r => r.total), 1);
            const c = PERSON_COLORS[idx % PERSON_COLORS.length];
            return (
              <div key={s.name} className="flex items-center gap-4">
                <span className="text-[#C5A059] font-serif text-lg w-8 text-right">#{idx + 1}</span>
                <div className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-medium flex-shrink-0" style={{ backgroundColor: `${c}20`, color: c }}>{s.name.charAt(0)}</div>
                <span className="text-white text-sm w-32 truncate">{s.name}</span>
                <div className="flex-1 h-6 bg-black/30 rounded-full overflow-hidden relative">
                  <div className="h-full rounded-full transition-all duration-700 flex items-center px-3" style={{ width: `${Math.max((s.total / maxTotal) * 100, 8)}%`, backgroundColor: `${c}40` }}>
                    <span className="text-white text-xs font-medium whitespace-nowrap">{s.total} leads | {s.deals_won ?? 0} won | {s.conversion_rate}%</span>
                  </div>
                </div>
              </div>
            );
          }))}
        </div>
      </motion.div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <motion.div initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.4 }} className="glass-card rounded-lg p-4">
          <h3 className="font-serif text-xl text-white mb-6">Leads Assigned vs Outcomes</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={comparisonData} margin={{ top: 10, right: 10, left: 0, bottom: 40 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis dataKey="name" stroke="#A1A1AA" tick={{ fill: '#A1A1AA', fontSize: 11 }} angle={-30} textAnchor="end" />
              <YAxis stroke="#52525B" tick={{ fill: '#A1A1AA', fontSize: 11 }} />
              <Tooltip content={<SalesBarTooltip />} />
              <Legend wrapperStyle={{ paddingTop: 10 }} />
              <Bar dataKey="Assigned" fill="#C5A059" radius={[4, 4, 0, 0]} />
              <Bar dataKey="In Site Visit Stage" fill="#14B8A6" radius={[4, 4, 0, 0]} />
              <Bar dataKey="Deals Won" fill="#10B981" radius={[4, 4, 0, 0]} />
              <Bar dataKey="Deals Lost" fill="#EF4444" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </motion.div>

        <motion.div initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.4 }} className="glass-card rounded-lg p-4">
          <h3 className="font-serif text-xl text-white mb-6">Nurturing Label Distribution</h3>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie data={nurtureDistribution} cx="50%" cy="50%" innerRadius={60} outerRadius={100} paddingAngle={4} dataKey="value">
                {nurtureDistribution.map((e, i) => <Cell key={i} fill={e.color} />)}
              </Pie>
              <Tooltip content={({ active, payload }) => active && payload?.length ? (
                <div className="bg-[#1A1A1A] border border-white/10 rounded-lg p-3 shadow-xl">
                  <p className="text-[#C5A059] font-medium">{payload[0].name}</p>
                  <p className="text-white">{payload[0].value} leads</p>
                </div>
              ) : null} />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </motion.div>
      </div>

      <AnimatePresence>
        {selectedPerson && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/60 flex items-start justify-center pt-10 overflow-y-auto pb-10"
            onClick={closeRepModal}>
            <motion.div initial={{ opacity: 0, y: 30, scale: 0.95 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 30, scale: 0.95 }}
              className="bg-[#0F0F0F] border border-white/10 rounded-xl w-full max-w-4xl mx-4 p-6 shadow-2xl"
              onClick={e => e.stopPropagation()} data-testid="drilldown-modal">
              <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-4">
                  <div className="w-12 h-12 rounded-full bg-[#C5A059]/20 flex items-center justify-center text-[#C5A059] text-xl font-serif">{selectedPerson.name.charAt(0)}</div>
                  <div>
                    <h2 className="font-serif text-2xl text-white">{selectedPerson.name}</h2>
                  <p className="text-[#A1A1AA] text-sm">{selectedPerson.total} leads assigned</p>
                  </div>
                </div>
                <Button variant="ghost" onClick={closeRepModal} className="text-[#A1A1AA] hover:text-white"><X size={20} /></Button>
              </div>

              <div className="grid grid-cols-6 gap-3 mb-6">
                {[
                  { label: 'Total Assigned', value: selectedPerson.total, color: 'text-[#C5A059]', bg: 'bg-[#C5A059]/10' },
                  { label: 'Contacted', value: selectedPerson.contacted ?? 0, color: 'text-blue-400', bg: 'bg-blue-500/10' },
                  { label: 'Site Visit Stage', value: selectedPerson.site_visits, color: 'text-teal-400', bg: 'bg-teal-500/10' },
                  { label: 'Negotiation', value: selectedPerson.negotiation ?? 0, color: 'text-purple-400', bg: 'bg-purple-500/10' },
                  { label: 'Deals Won', value: selectedPerson.deals_won ?? 0, color: 'text-green-400', bg: 'bg-green-500/10' },
                  { label: 'Deals Lost', value: selectedPerson.deals_lost ?? 0, color: 'text-red-400', bg: 'bg-red-500/10' },
                ].map((f, i) => (
                  <div key={f.label} className={`p-3 rounded-lg ${f.bg} text-center relative`}>
                    <p className="text-[#52525B] text-[10px] uppercase">{f.label}</p>
                    <p className={`font-serif text-2xl ${f.color}`}>{f.value}</p>
                    {i < 5 && <div className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-1/2 text-[#52525B] z-10">&#8594;</div>}
                  </div>
                ))}
              </div>

              <h3 className="font-serif text-lg text-white mb-3">All Assigned Leads</h3>
              <p className="text-[#52525B] text-xs mb-2">Showing {repLeads.length} of {repLeadsTotal}{repLeadsLoading ? ' · Loading…' : ''}</p>
              <div
                ref={listScrollRef}
                onScroll={onLeadListScroll}
                className="max-h-80 overflow-y-auto pr-2"
              >
                {useVirtualRepLeads ? (
                  <div
                    style={{
                      height: `${repListVirtualizer.getTotalSize()}px`,
                      width: '100%',
                      position: 'relative',
                    }}
                  >
                    {repListVirtualizer.getVirtualItems().map((vi) => {
                      const row = repLeadRows[vi.index];
                      return (
                        <div
                          key={row.lead.id}
                          style={{
                            position: 'absolute',
                            top: 0,
                            left: 0,
                            width: '100%',
                            transform: `translateY(${vi.start}px)`,
                          }}
                        >
                          <SalesDrilldownLeadRow
                            lead={row.lead}
                            formattedDate={row.formattedDate}
                            onSelect={handleDrilldownLeadSelect}
                          />
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="space-y-2">
                    {repLeadRows.map((row) => (
                      <SalesDrilldownLeadRow
                        key={row.lead.id}
                        lead={row.lead}
                        formattedDate={row.formattedDate}
                        onSelect={handleDrilldownLeadSelect}
                      />
                    ))}
                  </div>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default SalesDashboardPage;
