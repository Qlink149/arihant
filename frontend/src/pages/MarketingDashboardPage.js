import React, { useState, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { marketingAPI } from '../services/api';
import { toast } from 'sonner';
import {
  DollarSign, TrendingUp, Users, Target, Plus, X, Trash2,
  BarChart3, PieChart as PieChartIcon, ArrowUpRight, Layers, Filter
} from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell, Legend
} from 'recharts';
import { Button } from '../components/ui/button';

const CHANNEL_OPTIONS = [
  { value: 'meta_ads', label: 'Meta Ads (Facebook/Instagram)' },
  { value: 'google_ads', label: 'Google Ads' },
  { value: 'newspaper', label: 'Newspaper / Print' },
  { value: 'events', label: 'Events / Exhibitions' },
  { value: 'wati', label: 'WATI / WhatsApp' },
  { value: 'organic', label: 'Organic / SEO' },
  { value: 'referral', label: 'Referral' },
  { value: 'other', label: 'Other' },
];

const CHANNEL_COLORS = {
  meta_ads: '#1877F2',
  google_ads: '#EA4335',
  newspaper: '#F59E0B',
  events: '#8B5CF6',
  wati: '#25D366',
  organic: '#10B981',
  referral: '#EC4899',
  other: '#6B7280',
};

const CHART_COLORS = ['#C5A059', '#3B82F6', '#10B981', '#F59E0B', '#8B5CF6', '#EC4899', '#EF4444', '#14B8A6'];

const formatCurrency = (n) => {
  if (n >= 100000) return `${(n / 100000).toFixed(1)}L`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
  return n.toLocaleString('en-IN');
};

const MarketingDashboardPage = () => {
  const [dashData, setDashData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showAddForm, setShowAddForm] = useState(false);
  const [projectFilter, setProjectFilter] = useState('all');
  const [form, setForm] = useState({
    project: '', channel: 'meta_ads', amount: '', leads_generated: '',
    conversions: '', period: new Date().toISOString().slice(0, 7),
    campaign_name: '', impressions: '', clicks: '', notes: ''
  });

  useEffect(() => { fetchData(); }, []);

  const fetchData = async () => {
    try {
      const res = await marketingAPI.getDashboard();
      setDashData(res.data);
    } catch {
      toast.error('Failed to load marketing data');
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async () => {
    if (!form.project || !form.amount) {
      toast.error('Project and amount are required');
      return;
    }
    try {
      await marketingAPI.addSpend({
        ...form,
        amount: parseFloat(form.amount) || 0,
        leads_generated: parseInt(form.leads_generated) || 0,
        conversions: parseInt(form.conversions) || 0,
        impressions: form.impressions ? parseInt(form.impressions) : null,
        clicks: form.clicks ? parseInt(form.clicks) : null,
      });
      toast.success('Spend entry added');
      setShowAddForm(false);
      setForm({ project: '', channel: 'meta_ads', amount: '', leads_generated: '', conversions: '', period: new Date().toISOString().slice(0, 7), campaign_name: '', impressions: '', clicks: '', notes: '' });
      fetchData();
    } catch {
      toast.error('Failed to add entry');
    }
  };

  const handleDelete = async (id) => {
    try {
      await marketingAPI.deleteSpend(id);
      toast.success('Entry deleted');
      fetchData();
    } catch {
      toast.error('Failed to delete');
    }
  };

  const projects = useMemo(() => {
    if (!dashData?.by_project) return [];
    return dashData.by_project.map(p => p.project);
  }, [dashData]);

  const filteredEntries = useMemo(() => {
    if (!dashData?.entries) return [];
    if (projectFilter === 'all') return dashData.entries;
    return dashData.entries.filter(e => e.project === projectFilter);
  }, [dashData, projectFilter]);

  const channelChartData = useMemo(() => {
    if (!dashData?.by_channel) return [];
    return dashData.by_channel.map(c => ({
      name: CHANNEL_OPTIONS.find(o => o.value === c.channel)?.label || c.channel,
      spend: c.total_spend,
      leads: c.total_leads,
      cpl: c.cpl,
      color: CHANNEL_COLORS[c.channel] || '#6B7280',
    }));
  }, [dashData]);

  const projectChartData = useMemo(() => {
    if (!dashData?.by_project) return [];
    return dashData.by_project.map(p => ({
      name: p.project,
      spend: p.total_spend,
      leads: p.total_leads,
      conversions: p.total_conversions,
      cpl: p.cpl,
    }));
  }, [dashData]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-[#C5A059] animate-pulse text-lg">Loading marketing data...</div>
      </div>
    );
  }

  const totalSpend = dashData?.total_spend || 0;
  const totalLeads = dashData?.total_leads || 0;
  const totalConversions = dashData?.total_conversions || 0;
  const avgCPL = totalLeads > 0 ? Math.round(totalSpend / totalLeads) : 0;
  const hasData = (dashData?.entries || []).length > 0;

  const CustomTooltip = ({ active, payload, label }) => {
    if (active && payload?.length) {
      return (
        <div className="bg-[#1A1A1A] border border-white/10 rounded-lg p-3 shadow-xl">
          <p className="text-[#C5A059] font-medium text-sm mb-1">{label}</p>
          {payload.map((p, i) => (
            <p key={i} className="text-white text-xs">
              {p.name}: {p.name.includes('spend') || p.name === 'cpl' ? `₹${formatCurrency(p.value)}` : p.value}
            </p>
          ))}
        </div>
      );
    }
    return null;
  };

  return (
    <div className="space-y-3" data-testid="marketing-dashboard">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-white tracking-tight" data-testid="marketing-title">
            Marketing <span className="text-[#C5A059]">Dashboard</span>
          </h1>
          <p className="text-[#52525B] mt-1 text-sm">Track spends, leads generated, and ROI across channels</p>
        </div>
        <Button
          onClick={() => setShowAddForm(true)}
          className="bg-[#C5A059] hover:bg-[#B08D3E] text-black font-medium"
          data-testid="add-spend-btn"
        >
          <Plus size={16} className="mr-2" /> Add Spend Entry
        </Button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4" data-testid="marketing-metrics">
        {[
          { label: 'Total Spend', value: `₹${formatCurrency(totalSpend)}`, icon: DollarSign, color: 'text-[#C5A059]', bg: 'bg-[#C5A059]/10' },
          { label: 'Leads Generated', value: totalLeads, icon: Users, color: 'text-blue-400', bg: 'bg-blue-500/10' },
          { label: 'Conversions', value: totalConversions, icon: Target, color: 'text-emerald-500', bg: 'bg-emerald-500/10' },
          { label: 'Avg. CPL', value: `₹${formatCurrency(avgCPL)}`, icon: TrendingUp, color: 'text-purple-400', bg: 'bg-purple-500/10' },
        ].map((card, i) => (
          <motion.div
            key={card.label}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05 }}
            className="bg-[#1A1A1A] border border-white/5 rounded-xl p-5"
            data-testid={`metric-${card.label.toLowerCase().replace(/[\s.]/g, '-')}`}
          >
            <div className={`w-10 h-10 rounded-lg ${card.bg} flex items-center justify-center mb-3`}>
              <card.icon size={20} className={card.color} />
            </div>
            <p className="text-white text-2xl font-semibold">{card.value}</p>
            <p className="text-[#52525B] text-xs mt-1">{card.label}</p>
          </motion.div>
        ))}
      </div>

      {hasData ? (
        <>
          {/* Charts Row */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Spend by Channel */}
            <motion.div
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.2 }}
              className="bg-[#1A1A1A] border border-white/5 rounded-xl p-6"
              data-testid="channel-chart"
            >
              <h3 className="text-white font-medium mb-4 flex items-center gap-2">
                <PieChartIcon size={18} className="text-[#C5A059]" /> Spend by Channel
              </h3>
              <ResponsiveContainer width="100%" height={280}>
                <PieChart>
                  <Pie data={channelChartData} cx="50%" cy="50%" innerRadius={55} outerRadius={95} paddingAngle={4} dataKey="spend">
                    {channelChartData.map((entry, i) => (
                      <Cell key={i} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip content={<CustomTooltip />} />
                </PieChart>
              </ResponsiveContainer>
              <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 justify-center">
                {channelChartData.map(c => (
                  <div key={c.name} className="flex items-center gap-1.5">
                    <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: c.color }} />
                    <span className="text-[#A1A1AA] text-xs">{c.name}</span>
                  </div>
                ))}
              </div>
            </motion.div>

            {/* Spend by Project */}
            <motion.div
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.2 }}
              className="bg-[#1A1A1A] border border-white/5 rounded-xl p-6"
              data-testid="project-chart"
            >
              <h3 className="text-white font-medium mb-4 flex items-center gap-2">
                <BarChart3 size={18} className="text-[#C5A059]" /> Spend vs Leads by Project
              </h3>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={projectChartData} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis dataKey="name" stroke="#52525B" tick={{ fill: '#A1A1AA', fontSize: 11 }} />
                  <YAxis yAxisId="left" stroke="#52525B" tick={{ fill: '#A1A1AA', fontSize: 11 }} />
                  <YAxis yAxisId="right" orientation="right" stroke="#52525B" tick={{ fill: '#A1A1AA', fontSize: 11 }} />
                  <Tooltip content={<CustomTooltip />} />
                  <Bar yAxisId="left" dataKey="spend" name="spend" fill="#C5A059" radius={[4, 4, 0, 0]} />
                  <Bar yAxisId="right" dataKey="leads" name="leads" fill="#3B82F6" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
              <div className="flex gap-4 mt-2 justify-center">
                <div className="flex items-center gap-1.5"><div className="w-3 h-3 rounded bg-[#C5A059]" /><span className="text-[#A1A1AA] text-xs">Spend (₹)</span></div>
                <div className="flex items-center gap-1.5"><div className="w-3 h-3 rounded bg-[#3B82F6]" /><span className="text-[#A1A1AA] text-xs">Leads</span></div>
              </div>
            </motion.div>
          </div>

          {/* Project-wise breakdown table */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 }}
            className="bg-[#1A1A1A] border border-white/5 rounded-xl p-6"
            data-testid="project-breakdown"
          >
            <h3 className="text-white font-medium mb-4 flex items-center gap-2">
              <Layers size={18} className="text-[#C5A059]" /> Project-wise ROI Breakdown
            </h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/10">
                    <th className="text-left text-[#52525B] font-medium py-3 pr-4">Project</th>
                    <th className="text-right text-[#52525B] font-medium py-3 px-4">Spend</th>
                    <th className="text-right text-[#52525B] font-medium py-3 px-4">Leads</th>
                    <th className="text-right text-[#52525B] font-medium py-3 px-4">Conversions</th>
                    <th className="text-right text-[#52525B] font-medium py-3 px-4">CPL</th>
                    <th className="text-right text-[#52525B] font-medium py-3 pl-4">CPC</th>
                  </tr>
                </thead>
                <tbody>
                  {(dashData?.by_project || []).map((p, i) => (
                    <tr key={p.project} className="border-b border-white/5 hover:bg-white/[0.02]">
                      <td className="py-3 pr-4 text-white font-medium">{p.project}</td>
                      <td className="py-3 px-4 text-right text-[#A1A1AA]">₹{formatCurrency(p.total_spend)}</td>
                      <td className="py-3 px-4 text-right text-blue-400">{p.total_leads}</td>
                      <td className="py-3 px-4 text-right text-emerald-400">{p.total_conversions}</td>
                      <td className="py-3 px-4 text-right text-[#C5A059]">₹{formatCurrency(p.cpl)}</td>
                      <td className="py-3 pl-4 text-right text-purple-400">₹{formatCurrency(p.cpc)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </motion.div>
        </>
      ) : (
        <div className="text-center py-16 bg-[#1A1A1A] border border-white/5 rounded-xl" data-testid="empty-state">
          <BarChart3 className="mx-auto text-[#52525B]" size={48} />
          <h3 className="text-white font-medium mt-4">No marketing data yet</h3>
          <p className="text-[#52525B] text-sm mt-1 max-w-md mx-auto">
            Start by adding your marketing spend entries. Track spends across Meta Ads, Google, Print, Events and more.
          </p>
          <Button onClick={() => setShowAddForm(true)} className="mt-4 bg-[#C5A059] hover:bg-[#B08D3E] text-black font-medium" data-testid="empty-add-btn">
            <Plus size={16} className="mr-2" /> Add First Entry
          </Button>
        </div>
      )}

      {/* Recent Entries */}
      {hasData && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.35 }}
          className="bg-[#1A1A1A] border border-white/5 rounded-xl p-6"
          data-testid="recent-entries"
        >
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white font-medium">Recent Entries</h3>
            <div className="flex gap-2">
              {['all', ...projects].map(p => (
                <button
                  key={p}
                  onClick={() => setProjectFilter(p)}
                  className={`px-3 py-1 rounded-lg text-xs font-medium transition-all ${
                    projectFilter === p ? 'bg-[#C5A059]/20 text-[#C5A059]' : 'text-[#52525B] hover:text-[#A1A1AA] bg-white/5'
                  }`}
                  data-testid={`filter-${p}`}
                >
                  {p === 'all' ? 'All' : p}
                </button>
              ))}
            </div>
          </div>
          <div className="space-y-2">
            {filteredEntries.slice(0, 20).map(entry => (
              <div key={entry.id} className="flex items-center gap-4 py-3 border-b border-white/5 last:border-0 group">
                <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: CHANNEL_COLORS[entry.channel] || '#6B7280' }} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-white text-sm font-medium">{entry.project}</span>
                    <span className="text-[#52525B] text-xs">via {CHANNEL_OPTIONS.find(c => c.value === entry.channel)?.label || entry.channel}</span>
                  </div>
                  <div className="flex items-center gap-4 mt-0.5">
                    <span className="text-[#C5A059] text-xs">₹{formatCurrency(entry.amount)}</span>
                    <span className="text-blue-400 text-xs">{entry.leads_generated} leads</span>
                    <span className="text-emerald-400 text-xs">{entry.conversions} conv.</span>
                    <span className="text-[#52525B] text-xs">{entry.period}</span>
                    {entry.campaign_name && <span className="text-[#52525B] text-xs italic">{entry.campaign_name}</span>}
                  </div>
                </div>
                <button
                  onClick={() => handleDelete(entry.id)}
                  className="text-[#52525B] hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all p-1"
                  data-testid={`delete-entry-${entry.id}`}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        </motion.div>
      )}

      {/* Add Spend Modal */}
      <AnimatePresence>
        {showAddForm && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
            onClick={() => setShowAddForm(false)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-[#1A1A1A] border border-white/10 rounded-xl w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto"
              onClick={e => e.stopPropagation()}
              data-testid="add-spend-modal"
            >
              <div className="flex items-center justify-between mb-5">
                <h3 className="text-white font-semibold">Add Marketing Spend</h3>
                <button onClick={() => setShowAddForm(false)} className="text-[#52525B] hover:text-white"><X size={20} /></button>
              </div>

              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[#A1A1AA] text-xs mb-1.5 block">Project *</label>
                    <input
                      type="text"
                      value={form.project}
                      onChange={e => setForm(p => ({ ...p, project: e.target.value }))}
                      placeholder="e.g. ECR - Reserve 16"
                      className="w-full bg-[#0F0F0F] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm placeholder:text-[#52525B] focus:border-[#C5A059]/50 focus:outline-none"
                      data-testid="spend-project-input"
                    />
                  </div>
                  <div>
                    <label className="text-[#A1A1AA] text-xs mb-1.5 block">Channel *</label>
                    <select
                      value={form.channel}
                      onChange={e => setForm(p => ({ ...p, channel: e.target.value }))}
                      className="w-full bg-[#0F0F0F] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm focus:border-[#C5A059]/50 focus:outline-none"
                      data-testid="spend-channel-select"
                    >
                      {CHANNEL_OPTIONS.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-3">
                  <div>
                    <label className="text-[#A1A1AA] text-xs mb-1.5 block">Amount (₹) *</label>
                    <input
                      type="number"
                      value={form.amount}
                      onChange={e => setForm(p => ({ ...p, amount: e.target.value }))}
                      placeholder="50000"
                      className="w-full bg-[#0F0F0F] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm placeholder:text-[#52525B] focus:border-[#C5A059]/50 focus:outline-none"
                      data-testid="spend-amount-input"
                    />
                  </div>
                  <div>
                    <label className="text-[#A1A1AA] text-xs mb-1.5 block">Leads Generated</label>
                    <input
                      type="number"
                      value={form.leads_generated}
                      onChange={e => setForm(p => ({ ...p, leads_generated: e.target.value }))}
                      placeholder="0"
                      className="w-full bg-[#0F0F0F] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm placeholder:text-[#52525B] focus:border-[#C5A059]/50 focus:outline-none"
                      data-testid="spend-leads-input"
                    />
                  </div>
                  <div>
                    <label className="text-[#A1A1AA] text-xs mb-1.5 block">Conversions</label>
                    <input
                      type="number"
                      value={form.conversions}
                      onChange={e => setForm(p => ({ ...p, conversions: e.target.value }))}
                      placeholder="0"
                      className="w-full bg-[#0F0F0F] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm placeholder:text-[#52525B] focus:border-[#C5A059]/50 focus:outline-none"
                      data-testid="spend-conversions-input"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[#A1A1AA] text-xs mb-1.5 block">Period</label>
                    <input
                      type="month"
                      value={form.period}
                      onChange={e => setForm(p => ({ ...p, period: e.target.value }))}
                      className="w-full bg-[#0F0F0F] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm focus:border-[#C5A059]/50 focus:outline-none"
                      data-testid="spend-period-input"
                    />
                  </div>
                  <div>
                    <label className="text-[#A1A1AA] text-xs mb-1.5 block">Campaign Name</label>
                    <input
                      type="text"
                      value={form.campaign_name}
                      onChange={e => setForm(p => ({ ...p, campaign_name: e.target.value }))}
                      placeholder="Optional"
                      className="w-full bg-[#0F0F0F] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm placeholder:text-[#52525B] focus:border-[#C5A059]/50 focus:outline-none"
                      data-testid="spend-campaign-input"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[#A1A1AA] text-xs mb-1.5 block">Impressions</label>
                    <input
                      type="number"
                      value={form.impressions}
                      onChange={e => setForm(p => ({ ...p, impressions: e.target.value }))}
                      placeholder="Optional"
                      className="w-full bg-[#0F0F0F] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm placeholder:text-[#52525B] focus:border-[#C5A059]/50 focus:outline-none"
                      data-testid="spend-impressions-input"
                    />
                  </div>
                  <div>
                    <label className="text-[#A1A1AA] text-xs mb-1.5 block">Clicks</label>
                    <input
                      type="number"
                      value={form.clicks}
                      onChange={e => setForm(p => ({ ...p, clicks: e.target.value }))}
                      placeholder="Optional"
                      className="w-full bg-[#0F0F0F] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm placeholder:text-[#52525B] focus:border-[#C5A059]/50 focus:outline-none"
                      data-testid="spend-clicks-input"
                    />
                  </div>
                </div>

                <div>
                  <label className="text-[#A1A1AA] text-xs mb-1.5 block">Notes</label>
                  <textarea
                    value={form.notes}
                    onChange={e => setForm(p => ({ ...p, notes: e.target.value }))}
                    placeholder="Optional notes..."
                    rows={2}
                    className="w-full bg-[#0F0F0F] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm placeholder:text-[#52525B] focus:border-[#C5A059]/50 focus:outline-none resize-none"
                    data-testid="spend-notes-input"
                  />
                </div>

                <Button onClick={handleSubmit} className="w-full bg-[#C5A059] hover:bg-[#B08D3E] text-black font-medium" data-testid="submit-spend-btn">
                  Add Spend Entry
                </Button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default MarketingDashboardPage;
