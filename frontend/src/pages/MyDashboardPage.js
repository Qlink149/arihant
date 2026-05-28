import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { myDashboardAPI, tasksAPI } from '../services/api';
import { toast } from 'sonner';
import {
  CheckCircle,
  ArrowRightLeft, Eye, Calendar,
  User, Building, X, Search,
  ListChecks, Plus
} from 'lucide-react';
import { formatStatusDisplay } from '../utils/nurtureLabel';
import { getLeadInitials } from '../utils/leadTable';
import { Button } from '../components/ui/button';
import { LeadOverviewGrid } from '../components/dashboard/LeadOverviewGrid';
import { resolveDrillDown } from '../utils/leadOverview';
import { TemperatureBadge } from '../components/leads/TemperatureBadge';
import { formatDateTimeIST, parseApiDate } from '../utils/datetime';
import { buildPendingTaskMap, formatFollowUp } from '../utils/leadTable';

const LEADS_PAGE = 150;

const COMPLETED_TASK_STATUSES = new Set(['completed', 'done', 'cancelled']);

const formatTransferDate = (transfer) => {
  const raw = transfer?.transferred_at || transfer?.transferred_at_dt;
  if (!raw) return '—';
  return formatDateTimeIST(raw) || '—';
};

const STATUS_COLORS = {
  'Open': 'bg-blue-500/20 text-blue-400',
  'Follow Up 1': 'bg-amber-500/20 text-amber-400',
  'Follow Up 2': 'bg-amber-600/20 text-amber-500',
  'Site Visit Scheduled': 'bg-purple-500/20 text-purple-400',
  'Site Visit Completed': 'bg-green-500/20 text-green-400',
  'Advance Paid': 'bg-emerald-500/20 text-emerald-400',
  'RNR': 'bg-red-500/20 text-red-400',
  'Nurturing': 'bg-orange-500/20 text-orange-400',
  'Gone Cold': 'bg-gray-500/20 text-gray-400',
};

const MyDashboardPage = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [leads, setLeads] = useState([]);
  const [leadsTotal, setLeadsTotal] = useState(0);
  const [leadsLoading, setLeadsLoading] = useState(false);
  const [taskLeadOptions, setTaskLeadOptions] = useState([]);
  const [overviewRefreshToken, setOverviewRefreshToken] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [showTransferModal, setShowTransferModal] = useState(false);
  const [selectedLead, setSelectedLead] = useState(null);
  const [reps, setReps] = useState([]);
  const [transferTo, setTransferTo] = useState('');
  const [transferNotes, setTransferNotes] = useState('');
  const [transferring, setTransferring] = useState(false);
  const [activeTab, setActiveTab] = useState('leads');
  const [transferSubTab, setTransferSubTab] = useState('received');
  const [showCompletedTasks, setShowCompletedTasks] = useState(false);
  const [showAddTask, setShowAddTask] = useState(false);
  const [newTask, setNewTask] = useState({ description: '', due_date: '', priority: 'medium', lead_id: '' });

  const leadsFetchBusy = useRef(false);
  const leadsFetchGeneration = useRef(0);
  const leadsAbortRef = useRef(null);
  const listScrollRef = useRef(null);

  const transferAckStorageKey = useMemo(() => {
    const uid = user?.id || user?.full_name || 'anon';
    return `transferBannerAck:${uid}`;
  }, [user?.id, user?.full_name]);

  const [transferBannerAckMs, setTransferBannerAckMs] = useState(0);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(transferAckStorageKey);
      const n = raw ? Number(raw) : 0;
      setTransferBannerAckMs(Number.isFinite(n) ? n : 0);
    } catch {
      setTransferBannerAckMs(0);
    }
  }, [transferAckStorageKey]);

  const buildLeadsParams = useCallback((skip, search) => {
    const params = { skip, limit: LEADS_PAGE };
    const q = (search || '').trim();
    if (q) params.search = q;
    return params;
  }, []);

  const loadLeadsPage = useCallback(async (skip, { append } = { append: false }, overrides = {}) => {
    if (append && leadsFetchBusy.current) return;

    const requestGen = leadsFetchGeneration.current;
    let abortController;
    if (!append) {
      leadsAbortRef.current?.abort();
      abortController = new AbortController();
      leadsAbortRef.current = abortController;
    }

    leadsFetchBusy.current = true;
    setLeadsLoading(true);
    try {
      const search = overrides.search !== undefined ? overrides.search : searchQuery;
      const { data: res } = await myDashboardAPI.getLeads(
        buildLeadsParams(skip, search),
        abortController ? { signal: abortController.signal } : undefined
      );
      if (requestGen !== leadsFetchGeneration.current) return;

      setLeadsTotal(res.total ?? 0);
      const batch = res.leads || [];
      setLeads((prev) => {
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
    } catch (err) {
      if (err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError') return;
      toast.error('Failed to load leads');
    } finally {
      if (requestGen === leadsFetchGeneration.current) {
        setLeadsLoading(false);
      }
      leadsFetchBusy.current = false;
    }
  }, [searchQuery, buildLeadsParams]);

  const refreshAll = useCallback(async () => {
    try {
      const [dashRes, repsRes] = await Promise.all([
        myDashboardAPI.getData(),
        myDashboardAPI.getReps(),
      ]);
      setData(dashRes.data);
      setReps(repsRes.data || []);
      setOverviewRefreshToken((t) => t + 1);
      leadsFetchBusy.current = false;
      await loadLeadsPage(0, { append: false });
    } catch {
      toast.error('Failed to load dashboard');
    }
  }, [loadLeadsPage]);

  useEffect(() => {
    const init = async () => {
      try {
        const [dashRes, repsRes] = await Promise.all([
          myDashboardAPI.getData(),
          myDashboardAPI.getReps(),
        ]);
        setData(dashRes.data);
        setReps(repsRes.data || []);
      } catch {
        toast.error('Failed to load dashboard');
      } finally {
        setLoading(false);
      }
    };
    init();
  }, []);

  useEffect(() => {
    if (loading) return;
    const delay = searchQuery.trim() ? 400 : 0;
    const t = setTimeout(() => {
      leadsFetchGeneration.current += 1;
      setLeads([]);
      if (listScrollRef.current) listScrollRef.current.scrollTop = 0;
      loadLeadsPage(0, { append: false });
    }, delay);
    return () => clearTimeout(t);
  }, [searchQuery, loading, loadLeadsPage]);

  useEffect(() => {
    const tab = location.state?.activeTab;
    if (!tab) return;
    setActiveTab(tab);
    if (location.state?.transferSubTab) {
      setTransferSubTab(location.state.transferSubTab);
    }
    navigate(location.pathname, { replace: true, state: {} });
  }, [location.state, location.pathname, navigate]);

  useEffect(() => {
    if (!showAddTask) return;
    myDashboardAPI.getLeads({ skip: 0, limit: 50 })
      .then(({ data: res }) => setTaskLeadOptions(res.leads || []))
      .catch(() => {});
  }, [showAddTask]);

  const onLeadListScroll = () => {
    const el = listScrollRef.current;
    if (!el || leadsLoading) return;
    if (leads.length >= leadsTotal) return;
    const nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 80;
    if (nearBottom) {
      loadLeadsPage(leads.length, { append: true });
    }
  };

  const handleTransfer = async () => {
    if (!selectedLead || !transferTo) return;
    setTransferring(true);
    try {
      await myDashboardAPI.transferLead({
        lead_id: selectedLead.id,
        to_rep: transferTo,
        notes: transferNotes,
      });
      toast.success(`Lead transferred to ${transferTo}`);
      setShowTransferModal(false);
      setSelectedLead(null);
      setTransferTo('');
      setTransferNotes('');
      await refreshAll();
    } catch {
      toast.error('Transfer failed');
    } finally {
      setTransferring(false);
    }
  };

  // Transfers are one-way (no acknowledgement required).

  const handleTaskComplete = async (taskId) => {
    try {
      await tasksAPI.update(taskId, { status: 'completed' });
      toast.success('Task marked complete');
      await refreshAll();
    } catch {
      toast.error('Failed to update task');
    }
  };

  const handleCreateTask = async () => {
    if (!newTask.description || !newTask.due_date) {
      toast.error('Description and due date are required');
      return;
    }
    try {
      await tasksAPI.create(newTask);
      toast.success('Task created');
      setNewTask({ description: '', due_date: '', priority: 'medium', lead_id: '' });
      setShowAddTask(false);
      await refreshAll();
    } catch {
      toast.error('Failed to create task');
    }
  };

  const getGreeting = () => {
    const h = new Date().getHours();
    if (h < 12) return 'Good Morning';
    if (h < 17) return 'Good Afternoon';
    return 'Good Evening';
  };

  const m = data?.metrics || {};
  const incomingTransfers = useMemo(() => data?.transferred_leads || [], [data?.transferred_leads]);
  const outgoingTransfers = useMemo(() => data?.outgoing_transfers || [], [data?.outgoing_transfers]);
  const displayTransfers = transferSubTab === 'sent' ? outgoingTransfers : incomingTransfers;
  const latestIncomingTransferMs = useMemo(() => {
    if (!Array.isArray(incomingTransfers) || incomingTransfers.length === 0) return 0;
    let maxMs = 0;
    for (const t of incomingTransfers) {
      const raw = t?.transferred_at_dt || t?.transferred_at;
      const ms = parseApiDate(raw)?.getTime?.() ?? 0;
      if (ms > maxMs) maxMs = ms;
    }
    return maxMs;
  }, [incomingTransfers]);
  const showTransferBanner = incomingTransfers.length > 0 && latestIncomingTransferMs > transferBannerAckMs;
  const tasks = data?.my_tasks || [];
  const pendingTasks = tasks.filter((t) => t.status === 'pending');
  const completedTasks = tasks.filter((t) => COMPLETED_TASK_STATUSES.has(t.status));
  const pendingTaskMap = useMemo(() => buildPendingTaskMap(pendingTasks), [pendingTasks]);

  if (loading) {
    return (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="flex items-center justify-center min-h-[60vh]"
      >
        <div className="text-[#C5A059] animate-pulse text-lg">Loading your dashboard...</div>
      </motion.div>
    );
  }

  const handleLeadOverviewDrillDown = (drillDown) => {
    resolveDrillDown(drillDown, {
      navigate,
      setActiveTab,
      setTransferSubTab,
    });
  };

  const tabs = [
    { id: 'leads', label: 'My Leads', count: m.total_leads || 0 },
    { id: 'tasks', label: 'Tasks', count: pendingTasks.length },
    { id: 'transfers', label: 'Transfers', count: incomingTransfers.length + outgoingTransfers.length },
  ];

  return (
    <div className="space-y-6" data-testid="my-dashboard">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col sm:flex-row sm:items-end justify-between gap-4"
      >
        <motion.div
          initial={{ opacity: 0, x: -12 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.05 }}
        >
          <h1 className="text-2xl sm:text-3xl font-semibold text-white tracking-tight" data-testid="my-dashboard-greeting">
            {getGreeting()}, <span className="text-[#C5A059]">{data?.rep_name || user?.full_name || 'Rep'}</span>
          </h1>
          <p className="text-[#52525B] mt-1 text-sm">Your personalized sales workspace</p>
        </motion.div>
      </motion.div>

      <LeadOverviewGrid
        onDrillDown={handleLeadOverviewDrillDown}
        refreshToken={overviewRefreshToken}
      />

      {/* Transferred Leads Alert */}
      <AnimatePresence>
        {showTransferBanner && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="bg-amber-500/10 border border-amber-500/20 rounded-xl p-4"
            data-testid="transferred-leads-alert"
          >
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.1 }}
              className="flex items-center gap-3"
            >
              <ArrowRightLeft size={20} className="text-amber-500" />
              <motion.div
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.15 }}
                className="flex-1"
              >
                <p className="text-amber-400 font-medium text-sm">{incomingTransfers.length} lead(s) transferred to you</p>
                <p className="text-amber-500/60 text-xs mt-0.5">Review and acknowledge below</p>
              </motion.div>
              <Button
                size="sm"
                variant="outline"
                className="border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
                onClick={() => {
                  setActiveTab('transfers');
                  setTransferSubTab('received');
                  try {
                    localStorage.setItem(transferAckStorageKey, String(latestIncomingTransferMs || 0));
                  } catch {
                    // ignore
                  }
                  setTransferBannerAckMs(latestIncomingTransferMs || 0);
                }}
              >
                View
              </Button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Tabs */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="flex gap-1 bg-[#1A1A1A] p-1 rounded-lg w-fit border border-white/5"
        data-testid="dashboard-tabs"
      >
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 rounded-md text-sm font-medium transition-all ${
              activeTab === tab.id
                ? 'bg-[#C5A059]/20 text-[#C5A059]'
                : 'text-[#A1A1AA] hover:text-white hover:bg-white/5'
            }`}
            data-testid={`tab-${tab.id}`}
          >
            {tab.label}
            {tab.count > 0 && (
              <span className={`ml-2 px-1.5 py-0.5 rounded-full text-xs ${
                activeTab === tab.id ? 'bg-[#C5A059]/30 text-[#C5A059]' : 'bg-white/10 text-[#52525B]'
              }`}>{tab.count}</span>
            )}
          </button>
        ))}
      </motion.div>

      {/* Leads Tab */}
      {activeTab === 'leads' && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="space-y-4"
        >
          {/* Filters */}
          <div className="flex flex-col sm:flex-row gap-3">
            <motion.div
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              className="relative flex-1 max-w-md"
            >
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#52525B]" />
              <input
                type="text"
                placeholder="Search leads..."
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-4 py-2 bg-[#1A1A1A] border border-white/10 rounded-lg text-white text-sm placeholder:text-[#52525B] focus:border-[#C5A059]/50 focus:outline-none"
                data-testid="lead-search-input"
              />
            </motion.div>
          </div>

          {/* Leads List */}
          <p className="text-[#52525B] text-xs">
            Showing {leads.length} of {leadsTotal}{leadsLoading ? ' · Loading…' : ''}
          </p>
          <motion.div
            ref={listScrollRef}
            onScroll={onLeadListScroll}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.15 }}
            className="grid gap-3 max-h-[calc(100vh-22rem)] overflow-y-auto pr-2"
          >
            {leads.length === 0 && !leadsLoading ? (
              <div className="text-center py-12 text-[#52525B]">No leads match your filters</div>
            ) : (
              leads.map((lead) => {
                const statusDisplay = formatStatusDisplay(lead.lead_status, lead.temperature);
                const followUp = formatFollowUp(lead, pendingTasks, pendingTaskMap);
                const taskCount = pendingTaskMap?.get(lead.id) || 0;
                return (
                  <motion.div
                    key={lead.id}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    className="bg-[#1A1A1A] border border-white/5 rounded-xl p-4 hover:border-white/10 transition-all group"
                    data-testid={`lead-card-${lead.id}`}
                  >
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      className="flex items-center gap-4"
                    >
                      <div className="w-10 h-10 rounded-lg bg-[#C5A059]/15 flex items-center justify-center flex-shrink-0 text-[#C5A059] text-xs font-semibold">
                        {getLeadInitials(lead)}
                      </div>
                      <motion.div
                        initial={{ opacity: 0, x: -6 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: 0.05 }}
                        className="flex-1 min-w-0"
                      >
                        <motion.div
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          className="flex items-center gap-2"
                        >
                          <p className="text-white font-medium text-sm truncate">
                            {lead.first_name} {lead.last_name}
                          </p>
                          {lead.vip && <span className="text-[10px] bg-[#C5A059]/20 text-[#C5A059] px-1.5 py-0.5 rounded-full">VIP</span>}
                        </motion.div>
                        <div className="flex items-center gap-3 mt-1">
                          <span className="text-[#52525B] text-xs flex items-center gap-1">
                            <Building size={11} /> {lead.project || 'No project'}
                          </span>
                          {data?.is_manager && (lead.assigned_to || lead.assigned_to_name) && (
                            <span className="text-[#52525B] text-xs flex items-center gap-1">
                              <User size={11} /> {lead.assigned_to || lead.assigned_to_name}
                            </span>
                          )}
                          {lead.lead_status === 'Nurturing' && (lead.temperature === 'Hot' || lead.temperature === 'Warm') ? (
                            <span className="inline-flex items-center gap-1.5">
                              <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[lead.lead_status] || 'bg-gray-500/20 text-gray-400'}`}>
                                Nurturing
                              </span>
                              <TemperatureBadge temperature={lead.temperature} />
                            </span>
                          ) : (
                            <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_COLORS[lead.lead_status] || 'bg-gray-500/20 text-gray-400'}`}>
                              {statusDisplay}
                            </span>
                          )}
                        </div>
                        <div className="flex flex-wrap items-center gap-3 mt-2">
                          <span className="text-[#A1A1AA] text-xs flex items-center gap-1">
                            <Calendar size={11} className="text-[#52525B]" />
                            {followUp ? (
                              <span className="text-white/90 font-medium">{followUp}</span>
                            ) : (
                              <span className="text-[#52525B]">—</span>
                            )}
                          </span>
                          <span className="text-[#A1A1AA] text-xs flex items-center gap-1">
                            <ListChecks size={11} className="text-[#52525B]" />
                            {taskCount > 0 ? (
                              <span className="text-amber-300 font-medium">{taskCount} pending</span>
                            ) : (
                              <span className="text-[#52525B]">—</span>
                            )}
                          </span>
                        </div>
                      </motion.div>
                      <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-[#A1A1AA] hover:text-white h-8 w-8 p-0"
                          onClick={() => navigate(`/lead/${lead.id}`)}
                          data-testid={`view-lead-${lead.id}`}
                        >
                          <Eye size={16} />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-[#A1A1AA] hover:text-amber-400 h-8 w-8 p-0"
                          onClick={() => { setSelectedLead(lead); setShowTransferModal(true); }}
                          data-testid={`transfer-lead-${lead.id}`}
                        >
                          <ArrowRightLeft size={16} />
                        </Button>
                      </div>
                    </motion.div>
                  </motion.div>
                );
              })
            )}
          </motion.div>
        </motion.div>
      )}

      {/* Tasks Tab */}
      {activeTab === 'tasks' && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-3"
          data-testid="tasks-section"
        >
          <div className="flex flex-wrap items-center gap-2">
            {!showAddTask ? (
              <Button
                onClick={() => setShowAddTask(true)}
                className="bg-[#C5A059] hover:bg-[#B08D3E] text-black font-medium"
                data-testid="add-task-btn"
              >
                <Plus size={16} className="mr-2" /> Add New Task
              </Button>
            ) : null}
            <Button
              variant="outline"
              onClick={() => setShowCompletedTasks((v) => !v)}
              className={`border-white/10 text-white hover:bg-white/5 ${
                showCompletedTasks ? 'border-[#C5A059] text-[#C5A059]' : ''
              }`}
              data-testid="toggle-completed-tasks"
            >
              <CheckCircle size={14} className="mr-2" />
              Completed ({m.completed_tasks ?? completedTasks.length})
            </Button>
          </div>

          {showAddTask ? (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              className="bg-[#1A1A1A] border border-[#C5A059]/20 rounded-xl p-5 space-y-4"
              data-testid="add-task-form"
            >
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex items-center justify-between"
              >
                <h4 className="text-white font-medium text-sm">New Task</h4>
                <button onClick={() => setShowAddTask(false)} className="text-[#52525B] hover:text-white">
                  <X size={18} />
                </button>
              </motion.div>
              <div>
                <label className="text-[#A1A1AA] text-xs mb-1.5 block">Description *</label>
                <input
                  type="text"
                  value={newTask.description}
                  onChange={e => setNewTask(p => ({ ...p, description: e.target.value }))}
                  placeholder="e.g. Follow up with client about site visit"
                  className="w-full bg-[#0F0F0F] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm placeholder:text-[#52525B] focus:border-[#C5A059]/50 focus:outline-none"
                  data-testid="task-description-input"
                />
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }}>
                  <label className="text-[#A1A1AA] text-xs mb-1.5 block">Due Date *</label>
                  <input
                    type="date"
                    value={newTask.due_date}
                    onChange={e => setNewTask(p => ({ ...p, due_date: e.target.value }))}
                    className="w-full bg-[#0F0F0F] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm focus:border-[#C5A059]/50 focus:outline-none"
                    data-testid="task-due-date-input"
                  />
                </motion.div>
                <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 }}>
                  <label className="text-[#A1A1AA] text-xs mb-1.5 block">Priority</label>
                  <select
                    value={newTask.priority}
                    onChange={e => setNewTask(p => ({ ...p, priority: e.target.value }))}
                    className="w-full bg-[#0F0F0F] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm focus:border-[#C5A059]/50 focus:outline-none"
                    data-testid="task-priority-select"
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                </motion.div>
                <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.11 }}>
                  <label className="text-[#A1A1AA] text-xs mb-1.5 block">Link to Lead</label>
                  <select
                    value={newTask.lead_id}
                    onChange={e => setNewTask(p => ({ ...p, lead_id: e.target.value }))}
                    className="w-full bg-[#0F0F0F] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm focus:border-[#C5A059]/50 focus:outline-none"
                    data-testid="task-lead-select"
                  >
                    <option value="">None</option>
                    {taskLeadOptions.map(l => (
                      <option key={l.id} value={l.id}>
                        {l.first_name} {l.last_name}
                      </option>
                    ))}
                  </select>
                </motion.div>
              </div>
              <div className="flex gap-2 justify-end">
                <Button variant="ghost" className="text-[#A1A1AA] hover:text-white" onClick={() => setShowAddTask(false)} data-testid="cancel-task-btn">
                  Cancel
                </Button>
                <Button onClick={handleCreateTask} className="bg-[#C5A059] hover:bg-[#B08D3E] text-black font-medium" data-testid="save-task-btn">
                  Create Task
                </Button>
              </div>
            </motion.div>
          ) : null}

          {!showCompletedTasks && pendingTasks.length === 0 && !showAddTask ? (
            <div className="text-center py-12 bg-[#1A1A1A] border border-white/5 rounded-xl">
              <ListChecks className="mx-auto text-[#52525B]" size={32} />
              <p className="text-[#52525B] mt-2 text-sm">All caught up! No pending tasks.</p>
            </div>
          ) : !showCompletedTasks ? (
            pendingTasks.map((task, i) => {
              const isOverdue = task.due_date && task.due_date < new Date().toISOString().split('T')[0];
              return (
                <motion.div
                  key={task.id}
                  initial={{ opacity: 0, y: 5 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: Math.min(i * 0.03, 0.3) }}
                  className={`bg-[#1A1A1A] border rounded-xl p-4 ${isOverdue ? 'border-red-500/30' : 'border-white/5'}`}
                  data-testid={`task-${task.id}`}
                >
                  <div className="flex items-start gap-3">
                    <button
                      onClick={() => handleTaskComplete(task.id)}
                      className={`w-5 h-5 rounded-full border-2 flex items-center justify-center flex-shrink-0 mt-0.5 transition-colors ${
                        isOverdue ? 'border-red-500 hover:bg-red-500/20' : 'border-[#52525B] hover:border-[#C5A059]'
                      }`}
                      data-testid={`task-complete-${task.id}`}
                    >
                      <CheckCircle size={10} className="opacity-0 hover:opacity-100" />
                    </button>
                    <div className="flex-1 min-w-0">
                      <p className="text-white text-sm">{task.description}</p>
                      <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        transition={{ delay: 0.05 }}
                        className="flex items-center gap-3 mt-1.5"
                      >
                        {task.lead_name && (
                          <span className="text-[#52525B] text-xs flex items-center gap-1">
                            <User size={10} /> {task.lead_name}
                          </span>
                        )}
                        {task.due_date && (
                          <span className={`text-xs flex items-center gap-1 ${isOverdue ? 'text-red-400' : 'text-[#52525B]'}`}>
                            <Calendar size={10} /> {task.due_date}
                          </span>
                        )}
                        <span className={`text-[10px] px-1.5 py-0.5 rounded-full uppercase tracking-wider ${
                          task.priority === 'high' ? 'bg-red-500/20 text-red-400' :
                          task.priority === 'medium' ? 'bg-amber-500/20 text-amber-400' :
                          'bg-gray-500/20 text-gray-400'
                        }`}>{task.priority || 'normal'}</span>
                      </motion.div>
                    </div>
                    {isOverdue && <span className="text-red-400 text-xs font-medium flex-shrink-0">Overdue</span>}
                  </div>
                </motion.div>
              );
            })
          ) : null}

          {showCompletedTasks && (
            completedTasks.length === 0 ? (
              <div className="text-center py-8 bg-[#1A1A1A] border border-white/5 rounded-xl">
                <p className="text-[#52525B] text-sm">No completed tasks yet</p>
              </div>
            ) : (
              completedTasks.map((task, i) => (
                <motion.div
                  key={task.id}
                  initial={{ opacity: 0, y: 5 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="bg-[#1A1A1A] border border-emerald-500/20 rounded-xl p-4 opacity-80"
                  data-testid={`completed-task-${task.id}`}
                >
                  <div className="flex items-start gap-3">
                    <CheckCircle size={18} className="text-emerald-500 flex-shrink-0 mt-0.5" />
                    <div className="flex-1 min-w-0">
                      <p className="text-[#A1A1AA] text-sm line-through">{task.description}</p>
                      <p className="text-[#52525B] text-xs mt-1">
                        {task.completed_at
                          ? `Completed ${formatTransferDate({ transferred_at: task.completed_at })}`
                          : 'Completed'}
                        {task.due_date ? ` · Due ${task.due_date}` : ''}
                      </p>
                    </div>
                  </div>
                </motion.div>
              ))
            )
          )}
        </motion.div>
      )}

      {/* Transfers Tab */}
      {activeTab === 'transfers' && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-3"
          data-testid="transfers-section"
        >
          <div className="flex gap-2 border-b border-white/5 pb-2" data-testid="transfer-subtabs">
            <button
              type="button"
              onClick={() => setTransferSubTab('received')}
              className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
                transferSubTab === 'received'
                  ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                  : 'text-[#52525B] hover:text-white'
              }`}
              data-testid="transfer-subtab-received"
            >
              Received ({incomingTransfers.length})
            </button>
            <button
              type="button"
              onClick={() => setTransferSubTab('sent')}
              className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
                transferSubTab === 'sent'
                  ? 'bg-teal-500/10 text-teal-400 border border-teal-500/20'
                  : 'text-[#52525B] hover:text-white'
              }`}
              data-testid="transfer-subtab-sent"
            >
              Sent ({outgoingTransfers.length})
            </button>
          </div>

          {displayTransfers.length === 0 ? (
            <motion.div
              initial={{ opacity: 0, scale: 0.98 }}
              animate={{ opacity: 1, scale: 1 }}
              className="text-center py-12 bg-[#1A1A1A] border border-white/5 rounded-xl"
            >
              <ArrowRightLeft className="mx-auto text-[#52525B]" size={32} />
              <p className="text-[#52525B] mt-2 text-sm">
                {transferSubTab === 'sent' ? 'No sent transfers' : 'No received transfers'}
              </p>
            </motion.div>
          ) : (
            displayTransfers.map((t, i) => (
              <motion.div
                key={t.id}
                initial={{ opacity: 0, y: 5 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: Math.min(i * 0.03, 0.3) }}
                className={`bg-[#1A1A1A] border rounded-xl p-4 ${
                  transferSubTab === 'sent' ? 'border-teal-500/20' : 'border-amber-500/20'
                }`}
                data-testid={`transfer-${t.id}`}
              >
                <div className="flex items-start gap-3">
                  <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${
                    transferSubTab === 'sent' ? 'bg-teal-500/10' : 'bg-amber-500/10'
                  }`}>
                    <ArrowRightLeft size={18} className={transferSubTab === 'sent' ? 'text-teal-500' : 'text-amber-500'} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-white font-medium text-sm">{t.lead_name}</p>
                    <p className="text-[#52525B] text-xs mt-0.5">
                      {transferSubTab === 'sent' ? (
                        <>
                          To <span className="text-[#A1A1AA]">{t.to_rep}</span>
                        </>
                      ) : (
                        <>
                          From <span className="text-[#A1A1AA]">{t.from_rep}</span>
                        </>
                      )}
                      {' '}&middot; {t.project}
                    </p>
                    {t.notes && <p className="text-[#52525B] text-xs mt-1 italic">&ldquo;{t.notes}&rdquo;</p>}
                    <p className="text-[#52525B] text-[10px] mt-1">{formatTransferDate(t)}</p>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-[#A1A1AA] hover:text-white h-8"
                      onClick={() => navigate(`/lead/${t.lead_id}`)}
                      data-testid={`view-transfer-lead-${t.id}`}
                    >
                      <Eye size={14} className="mr-1" /> View
                    </Button>
                    {/* no acknowledgement flow */}
                  </div>
                </div>
              </motion.div>
            ))
          )}
        </motion.div>
      )}

      {/* Transfer Modal */}
      <AnimatePresence>
        {showTransferModal && selectedLead && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
            onClick={() => setShowTransferModal(false)}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="bg-[#1A1A1A] border border-white/10 rounded-xl w-full max-w-md p-6"
              onClick={e => e.stopPropagation()}
              data-testid="transfer-modal"
            >
              <div className="flex items-center justify-between mb-5">
                <h3 className="text-white font-semibold">Transfer Lead</h3>
                <button onClick={() => setShowTransferModal(false)} className="text-[#52525B] hover:text-white">
                  <X size={20} />
                </button>
              </div>

              <div className="bg-[#0F0F0F] rounded-lg p-3 mb-4 border border-white/5">
                <p className="text-white text-sm font-medium">{selectedLead.first_name} {selectedLead.last_name}</p>
                <p className="text-[#52525B] text-xs mt-0.5">{selectedLead.project} &middot; {selectedLead.lead_status}</p>
              </div>

              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="space-y-4"
              >
                <div>
                  <label className="text-[#A1A1AA] text-xs mb-1.5 block">Transfer to</label>
                  <select
                    value={transferTo}
                    onChange={e => setTransferTo(e.target.value)}
                    className="w-full bg-[#0F0F0F] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm focus:border-[#C5A059]/50 focus:outline-none"
                    data-testid="transfer-to-select"
                  >
                    <option value="">Select a rep...</option>
                    {reps.filter(r => r.name !== data?.rep_name).map(r => (
                      <option key={r.name} value={r.name}>
                        {r.name} ({r.active_leads} active) - {r.status}
                      </option>
                    ))}
                  </select>
                </div>
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.05 }}>
                  <label className="text-[#A1A1AA] text-xs mb-1.5 block">Notes (optional)</label>
                  <textarea
                    value={transferNotes}
                    onChange={e => setTransferNotes(e.target.value)}
                    placeholder="Reason for transfer, handover notes..."
                    rows={3}
                    className="w-full bg-[#0F0F0F] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm placeholder:text-[#52525B] focus:border-[#C5A059]/50 focus:outline-none resize-none"
                    data-testid="transfer-notes-input"
                  />
                </motion.div>
                <Button
                  onClick={handleTransfer}
                  disabled={!transferTo || transferring}
                  className="w-full bg-[#C5A059] hover:bg-[#B08D3E] text-black font-medium disabled:opacity-50"
                  data-testid="confirm-transfer-btn"
                >
                  {transferring ? 'Transferring...' : 'Transfer Lead'}
                </Button>
              </motion.div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default MyDashboardPage;
