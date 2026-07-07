import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { motion, AnimatePresence } from 'framer-motion';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { myDashboardAPI, tasksAPI, usersAPI } from '../services/api';
import { toast } from 'sonner';
import {
  CheckCircle,
  ArrowRightLeft, Eye, X, Search,
  Plus, ListChecks
} from 'lucide-react';
import { formatStatusDisplay } from '../utils/nurtureLabel';
import { Button } from '../components/ui/button';
import { CrmBadge } from '../components/ui/CrmBadge';
import { LeadOverviewGrid } from '../components/dashboard/LeadOverviewGrid';
import { MyDashboardLeadCard } from '../components/dashboard/MyDashboardLeadCard';
import {
  shouldUseVirtualList,
  VIRTUAL_CARD_ESTIMATE_PX,
} from '../constants/performanceFlags';
import { useInfiniteScrollNearBottom } from '../hooks/useInfiniteScrollNearBottom';
import { useStatsAutoRefresh } from '../hooks/useStatsAutoRefresh';
import { resolveDrillDown } from '../utils/leadOverview';
import { dashboardMetricsChanged, metricsCountsChanged } from '../utils/shallowCompare';
import { formatDateTimeIST, parseApiDate } from '../utils/datetime';
import { buildEarliestPendingTaskMap, buildPendingTaskMap, formatFollowUp } from '../utils/leadTable';
import { TaskDetailModal } from '../components/tasks/TaskDetailModal';
import { TaskCard } from '../components/tasks/TaskCard';
import { TaskEditModal } from '../components/tasks/TaskEditModal';
import { TaskCompleteModal } from '../components/tasks/TaskCompleteModal';
import { LeadTasksDrawer } from '../components/tasks/LeadTasksDrawer';

const LEADS_PAGE = 150;
const STATS_REFRESH_MS = 60_000;

const COMPLETED_TASK_STATUSES = new Set(['completed', 'done', 'cancelled']);

const formatTransferDate = (transfer) => {
  const raw = transfer?.transferred_at || transfer?.transferred_at_dt;
  if (!raw) return '—';
  return formatDateTimeIST(raw) || '—';
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
  const [overviewMetrics, setOverviewMetrics] = useState([]);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [overviewError, setOverviewError] = useState(null);
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
  const [taskDetailOpen, setTaskDetailOpen] = useState(false);
  const [selectedTask, setSelectedTask] = useState(null);
  const [taskEditOpen, setTaskEditOpen] = useState(false);
  const [editingTask, setEditingTask] = useState(null);
  const [savingTaskEdit, setSavingTaskEdit] = useState(false);
  const [taskCompleteOpen, setTaskCompleteOpen] = useState(false);
  const [completingTask, setCompletingTask] = useState(false);

  const [leadTasksDrawerOpen, setLeadTasksDrawerOpen] = useState(false);
  const [leadTasksDrawerLead, setLeadTasksDrawerLead] = useState(null);
  const [leadTasksDrawerTasks, setLeadTasksDrawerTasks] = useState([]);
  const [leadTasksDrawerLoading, setLeadTasksDrawerLoading] = useState(false);
  const [leadTasksDrawerHighlightId, setLeadTasksDrawerHighlightId] = useState(null);

  const [selectedRepUserId, setSelectedRepUserId] = useState(null);
  const [repAssignees, setRepAssignees] = useState([]);
  const [leadsMetricFilter, setLeadsMetricFilter] = useState(null);

  const leadsFetchBusy = useRef(false);
  const leadsFetchGeneration = useRef(0);
  const leadsAbortRef = useRef(null);
  const listScrollRef = useRef(null);
  const repChangeMounted = useRef(false);

  const canSwitchRep = useMemo(() => {
    const role = (user?.role || '').toLowerCase();
    return role === 'admin' || role === 'manager';
  }, [user?.role]);

  const repParams = useMemo(
    () => (selectedRepUserId ? { rep_user_id: selectedRepUserId } : {}),
    [selectedRepUserId]
  );

  const viewingAs = Boolean(selectedRepUserId) || Boolean(data?.viewing_as);

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

  const buildLeadsParams = useCallback((skip, search, extra = {}) => {
    const params = { skip, limit: LEADS_PAGE, ...repParams };
    const q = (search || '').trim();
    if (q) params.search = q;
    const metric = extra.metric !== undefined ? extra.metric : leadsMetricFilter;
    if (metric) params.metric = metric;
    return params;
  }, [repParams, leadsMetricFilter]);

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
        buildLeadsParams(skip, search, { metric: overrides.metric }),
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

  const fetchOverview = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setOverviewLoading(true);
    setOverviewError(null);
    try {
      const { data } = await myDashboardAPI.getLeadOverview(repParams);
      const next = Array.isArray(data?.metrics) ? data.metrics : [];
      setOverviewMetrics((prev) => (metricsCountsChanged(prev, next) ? next : prev));
    } catch {
      if (!silent) {
        setOverviewError('Could not load lead overview');
        setOverviewMetrics([]);
      }
    } finally {
      if (!silent) setOverviewLoading(false);
    }
  }, [repParams]);

  const refreshAll = useCallback(async () => {
    try {
      const [dashRes, repsRes] = await Promise.all([
        myDashboardAPI.getData(repParams),
        myDashboardAPI.getReps(),
      ]);
      setData(dashRes.data);
      setReps(repsRes.data || []);
      await fetchOverview({ silent: true });
      leadsFetchBusy.current = false;
      await loadLeadsPage(0, { append: false });
    } catch {
      toast.error('Failed to load dashboard');
    }
  }, [loadLeadsPage, fetchOverview, repParams]);

  useEffect(() => {
    if (!canSwitchRep) return;
    usersAPI.listAssignees()
      .then(({ data: rows }) => {
        const list = (Array.isArray(rows) ? rows : [])
          .filter((a) => {
            if (a.is_active === false) return false;
            const role = (a.role || '').toLowerCase();
            return role === 'rep' || role === 'manager';
          })
          .sort((a, b) => (a.full_name || '').localeCompare(b.full_name || ''));
        setRepAssignees(list);
      })
      .catch(() => setRepAssignees([]));
  }, [canSwitchRep]);

  useEffect(() => {
    const init = async () => {
      try {
        const [dashRes, repsRes] = await Promise.all([
          myDashboardAPI.getData(),
          myDashboardAPI.getReps(),
        ]);
        setData(dashRes.data);
        setReps(repsRes.data || []);
        await fetchOverview();
      } catch {
        toast.error('Failed to load dashboard');
      } finally {
        setLoading(false);
      }
    };
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (loading) return;
    if (!repChangeMounted.current) {
      repChangeMounted.current = true;
      return;
    }
    setLeads([]);
    setLeadsMetricFilter(null);
    leadsFetchGeneration.current += 1;
    if (listScrollRef.current) listScrollRef.current.scrollTop = 0;
    (async () => {
      try {
        const { data: dashRes } = await myDashboardAPI.getData(repParams);
        setData(dashRes);
        await fetchOverview({ silent: true });
        await loadLeadsPage(0, { append: false });
      } catch {
        toast.error('Failed to load dashboard');
      }
    })();
  }, [selectedRepUserId]); // eslint-disable-line react-hooks/exhaustive-deps

  useStatsAutoRefresh(async () => {
    if (loading || !data) return;
    try {
      const [{ data: dashRes }, { data: overviewRes }] = await Promise.all([
        myDashboardAPI.getData(repParams),
        myDashboardAPI.getLeadOverview(repParams),
      ]);
      setData((prev) => (dashboardMetricsChanged(prev, dashRes) ? dashRes : prev));
      const nextMetrics = Array.isArray(overviewRes?.metrics) ? overviewRes.metrics : [];
      setOverviewMetrics((prev) => (metricsCountsChanged(prev, nextMetrics) ? nextMetrics : prev));
    } catch {
      /* silent refresh */
    }
  }, { intervalMs: STATS_REFRESH_MS, enabled: Boolean(data) });

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
    if (!showAddTask || viewingAs) return;
    myDashboardAPI.getLeads({ skip: 0, limit: 50, ...repParams })
      .then(({ data: res }) => setTaskLeadOptions(res.leads || []))
      .catch(() => {});
  }, [showAddTask, viewingAs, repParams]);

  const handleLeadListNearBottom = useCallback(() => {
    if (leadsLoading) return;
    if (leads.length >= leadsTotal) return;
    loadLeadsPage(leads.length, { append: true });
  }, [leadsLoading, leads.length, leadsTotal, loadLeadsPage]);

  const onLeadListScroll = useInfiniteScrollNearBottom(listScrollRef, handleLeadListNearBottom);

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

  const handleTaskComplete = async (taskId, patch = { status: 'completed' }) => {
    try {
      await tasksAPI.update(taskId, patch);
      toast.success('Task marked complete');
      await refreshAll();
    } catch (e) {
      const msg = e?.response?.data?.detail || 'Failed to update task';
      toast.error(typeof msg === 'string' ? msg : 'Failed to update task');
      throw e;
    }
  };

  const openTaskDetail = (task) => {
    if (!task) return;
    setSelectedTask(task);
    setTaskDetailOpen(true);
  };

  const handleCompleteFromModal = (task) => {
    if (!task?.id) return;
    setSelectedTask(task);
    setTaskDetailOpen(false);
    setTaskCompleteOpen(true);
  };

  const handleConfirmTaskComplete = async (task, patch) => {
    if (!task?.id) return;
    setCompletingTask(true);
    try {
      await handleTaskComplete(task.id, patch);
      setTaskCompleteOpen(false);
      setSelectedTask(null);
    } finally {
      setCompletingTask(false);
    }
  };

  const handleOpenLeadFromTask = (leadId) => {
    if (!leadId) return;
    setTaskDetailOpen(false);
    setTaskEditOpen(false);
    setSelectedTask(null);
    setEditingTask(null);
    navigate(`/lead/${leadId}`);
  };

  const openTaskEdit = (task) => {
    if (!task) return;
    setEditingTask(task);
    setTaskEditOpen(true);
  };

  const handleSaveTaskEdit = async (taskId, patch) => {
    if (!taskId) return;
    setSavingTaskEdit(true);
    try {
      await tasksAPI.update(taskId, patch);
      toast.success('Task updated');
      setTaskEditOpen(false);
      setEditingTask(null);
      await refreshAll();
    } catch {
      toast.error('Failed to update task');
    } finally {
      setSavingTaskEdit(false);
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

  const fetchLeadPendingTasks = useCallback(async (leadId) => {
    if (!leadId) return [];
    const { data: rows } = await tasksAPI.getAll({ status: 'pending', lead_id: leadId, mine: true });
    return Array.isArray(rows) ? rows : [];
  }, []);

  const openLeadTasksDrawer = useCallback(
    async (lead, { highlightTaskId = null } = {}) => {
      if (!lead?.id) return;
      setLeadTasksDrawerLead(lead);
      setLeadTasksDrawerTasks([]);
      setLeadTasksDrawerHighlightId(highlightTaskId);
      setLeadTasksDrawerOpen(true);
      setLeadTasksDrawerLoading(true);
      try {
        const list = await fetchLeadPendingTasks(lead.id);
        const sorted = [...list].sort((a, b) => {
          const ad = String(a?.due_date || '');
          const bd = String(b?.due_date || '');
          if (ad !== bd) return ad.localeCompare(bd);
          return String(b?.created_at || '').localeCompare(String(a?.created_at || ''));
        });
        setLeadTasksDrawerTasks(sorted);
      } catch {
        toast.error('Failed to load tasks for this lead');
      } finally {
        setLeadTasksDrawerLoading(false);
      }
    },
    [fetchLeadPendingTasks]
  );

  const handleCompleteDrawerTask = useCallback(
    async (task) => {
      const taskId = task?.id;
      const leadId = leadTasksDrawerLead?.id;
      if (!taskId) return;
      try {
        await tasksAPI.update(taskId, { status: 'completed' });
        toast.success('Task marked complete');
        if (leadId) {
          setLeadTasksDrawerLoading(true);
          const list = await fetchLeadPendingTasks(leadId);
          setLeadTasksDrawerTasks(list);
          setLeadTasksDrawerLoading(false);
        }
        await refreshAll();
      } catch {
        toast.error('Failed to update task');
      }
    },
    [leadTasksDrawerLead?.id, fetchLeadPendingTasks]
  );

  const handleOpenDrawerLead = useCallback(
    (leadId) => {
      if (!leadId) return;
      setLeadTasksDrawerOpen(false);
      navigate(`/lead/${leadId}`);
    },
    [navigate]
  );

  const getGreeting = () => {
    const h = new Date().getHours();
    if (h < 12) return 'Good Morning';
    if (h < 17) return 'Good Afternoon';
    return 'Good Evening';
  };

  const m = data?.metrics || {};
  const incomingTransfers = useMemo(() => data?.transferred_leads || [], [data?.transferred_leads]);
  const outgoingTransfers = useMemo(() => data?.outgoing_transfers || [], [data?.outgoing_transfers]);
  const incomingTransfersTotal = data?.incoming_transfers_total ?? data?.metrics?.leads_received ?? incomingTransfers.length;
  const outgoingTransfersTotal = data?.outgoing_transfers_total ?? data?.metrics?.leads_transferred ?? outgoingTransfers.length;
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
  const showTransferBanner = !viewingAs && incomingTransfers.length > 0 && latestIncomingTransferMs > transferBannerAckMs;
  const tasks = data?.my_tasks || [];
  const tasksSorted = useMemo(() => {
    const rows = Array.isArray(tasks) ? [...tasks] : [];
    const createdMs = (t) => {
      const raw = t?.created_at_dt || t?.created_at;
      return parseApiDate(raw)?.getTime?.() ?? 0;
    };
    // Most recent first (top). Fallback to id for determinism.
    rows.sort((a, b) => {
      const am = createdMs(a);
      const bm = createdMs(b);
      if (am !== bm) return bm - am;
      return String(b?.id || '').localeCompare(String(a?.id || ''));
    });
    return rows;
  }, [tasks]);

  const pendingTasks = tasksSorted.filter((t) => t.status === 'pending');
  const completedTasks = tasksSorted.filter((t) => COMPLETED_TASK_STATUSES.has(t.status));
  const pendingTaskMap = useMemo(() => buildPendingTaskMap(pendingTasks), [pendingTasks]);
  const earliestTaskMap = useMemo(
    () => buildEarliestPendingTaskMap(pendingTasks),
    [pendingTasks]
  );

  const leadCardRows = useMemo(() => {
    return leads.map((lead) => ({
      lead,
      statusDisplay: formatStatusDisplay(lead.lead_status, lead.temperature),
      followUp: formatFollowUp(lead, [], pendingTaskMap, earliestTaskMap),
      taskCount: pendingTaskMap?.get(lead.id) || 0,
    }));
  }, [leads, pendingTaskMap, earliestTaskMap]);

  const useVirtualLeads = shouldUseVirtualList(leads.length);

  const leadListVirtualizer = useVirtualizer({
    count: leadCardRows.length,
    getScrollElement: () => listScrollRef.current,
    estimateSize: () => VIRTUAL_CARD_ESTIMATE_PX,
    overscan: 8,
    enabled: useVirtualLeads,
    gap: 12,
  });

  const handleTransferLead = useCallback((lead) => {
    setSelectedLead(lead);
    setShowTransferModal(true);
  }, []);

  const handleLeadOverviewDrillDown = useCallback((drillDown) => {
    const viewing = Boolean(selectedRepUserId) || Boolean(data?.viewing_as);
    if (viewing && drillDown?.type === 'virtual_customer' && drillDown?.params?.metric) {
      const metric = drillDown.params.metric;
      setActiveTab('leads');
      setLeadsMetricFilter(metric);
      setSearchQuery('');
      leadsFetchGeneration.current += 1;
      setLeads([]);
      if (listScrollRef.current) listScrollRef.current.scrollTop = 0;
      loadLeadsPage(0, { append: false }, { metric, search: '' });
      return;
    }
    resolveDrillDown(drillDown, {
      navigate,
      setActiveTab,
      setTransferSubTab,
    });
  }, [navigate, selectedRepUserId, data?.viewing_as, loadLeadsPage]);

  const clearLeadsMetricFilter = useCallback(() => {
    setLeadsMetricFilter(null);
    leadsFetchGeneration.current += 1;
    setLeads([]);
    if (listScrollRef.current) listScrollRef.current.scrollTop = 0;
    loadLeadsPage(0, { append: false }, { metric: null });
  }, [loadLeadsPage]);

  const handleOpenLeadTasks = useCallback(
    (lead, opts) => openLeadTasksDrawer(lead, opts),
    [openLeadTasksDrawer],
  );

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

  const tabs = [
    { id: 'leads', label: 'My Leads', count: m.total_leads || 0 },
    { id: 'tasks', label: 'Tasks', count: pendingTasks.length },
    { id: 'transfers', label: 'Transfers', count: incomingTransfersTotal + outgoingTransfersTotal },
  ];

  return (
    <div className="space-y-3" data-testid="my-dashboard">
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
          <h1 className="text-xl font-semibold text-white tracking-tight" data-testid="my-dashboard-greeting">
            {getGreeting()}, <span className="text-[#C5A059]">{data?.rep_name || user?.full_name || 'Rep'}</span>
          </h1>
          <p className="text-[#52525B] mt-1 text-sm">
            {viewingAs ? 'Manager view of rep workspace' : 'Your personalized sales workspace'}
          </p>
        </motion.div>
        {canSwitchRep ? (
          <motion.div
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.05 }}
            className="sm:ml-auto w-full sm:w-auto"
          >
            <label htmlFor="rep-switcher-select" className="sr-only">View rep dashboard</label>
            <select
              id="rep-switcher-select"
              value={selectedRepUserId || ''}
              onChange={(e) => setSelectedRepUserId(e.target.value || null)}
              className="w-full sm:min-w-[220px] bg-[#1A1A1A] border border-white/10 rounded-lg px-3 py-2.5 text-white text-sm focus:border-[#C5A059]/50 focus:outline-none"
              data-testid="rep-switcher-select"
            >
              <option value="">My dashboard</option>
              {repAssignees.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.full_name}
                </option>
              ))}
            </select>
          </motion.div>
        ) : null}
      </motion.div>

      {viewingAs ? (
        <motion.div
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-[#C5A059]/10 border border-[#C5A059]/20 rounded-lg px-4 py-2 text-sm text-[#C5A059]"
          data-testid="viewing-as-banner"
        >
          Viewing <span className="font-medium text-white">{data?.rep_name || 'rep'}</span>&apos;s dashboard (read-only)
        </motion.div>
      ) : null}

      <LeadOverviewGrid
        onDrillDown={handleLeadOverviewDrillDown}
        metrics={overviewMetrics}
        loading={overviewLoading}
        error={overviewError}
        onRetry={() => fetchOverview()}
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
              <CrmBadge
                variant={activeTab === tab.id ? 'gold' : 'neutral'}
                size="xs"
                className="ml-2"
              >
                {tab.count}
              </CrmBadge>
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
          <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
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
            {leadsMetricFilter ? (
              <CrmBadge
                variant="gold"
                size="sm"
                className="flex items-center gap-1.5 pr-1"
                data-testid="leads-metric-filter"
              >
                <span>Filter: {leadsMetricFilter.replace(/_/g, ' ')}</span>
                <button
                  type="button"
                  onClick={clearLeadsMetricFilter}
                  className="hover:text-white rounded p-0.5"
                  aria-label="Clear metric filter"
                >
                  <X size={12} />
                </button>
              </CrmBadge>
            ) : null}
          </div>

          {/* Leads List */}
          <p className="text-[#52525B] text-xs">
            Showing {leads.length} of {leadsTotal}{leadsLoading ? ' · Loading…' : ''}
          </p>
          <div
            ref={listScrollRef}
            onScroll={onLeadListScroll}
            className="max-h-[calc(100vh-22rem)] overflow-y-auto pr-2"
          >
            {leads.length === 0 && !leadsLoading ? (
              <div className="text-center py-12 text-[#52525B]">No leads match your filters</div>
            ) : useVirtualLeads ? (
              <div
                style={{
                  height: `${leadListVirtualizer.getTotalSize()}px`,
                  width: '100%',
                  position: 'relative',
                }}
              >
                {leadListVirtualizer.getVirtualItems().map((vi) => {
                  const row = leadCardRows[vi.index];
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
                      <MyDashboardLeadCard
                        lead={row.lead}
                        followUp={row.followUp}
                        taskCount={row.taskCount}
                        statusDisplay={row.statusDisplay}
                        isManager={data?.is_manager}
                        onTransfer={viewingAs ? undefined : handleTransferLead}
                        onOpenTasks={handleOpenLeadTasks}
                        readOnly={viewingAs}
                      />
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="grid gap-3">
                {leadCardRows.map((row) => (
                  <MyDashboardLeadCard
                    key={row.lead.id}
                    lead={row.lead}
                    followUp={row.followUp}
                    taskCount={row.taskCount}
                    statusDisplay={row.statusDisplay}
                    isManager={data?.is_manager}
                    onTransfer={viewingAs ? undefined : handleTransferLead}
                    onOpenTasks={handleOpenLeadTasks}
                    readOnly={viewingAs}
                  />
                ))}
              </div>
            )}
          </div>
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
          <div className="rounded-xl border border-white/5 bg-[#1A1A1A] p-3" data-testid="tasks-hint">
            <p className="text-[#A1A1AA] text-sm">
              Each card shows lead, project, and reason at a glance. Use the circle to complete,
              or View Lead / Edit without opening full details. Click the card for more info.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {!showAddTask && !viewingAs ? (
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
            pendingTasks.map((task, i) => (
              <TaskCard
                key={task.id}
                task={task}
                variant="pending"
                index={i}
                onComplete={viewingAs ? undefined : (t) => handleCompleteFromModal(t)}
                onViewLead={handleOpenLeadFromTask}
                onEdit={viewingAs ? undefined : openTaskEdit}
                onOpenDetail={openTaskDetail}
              />
            ))
          ) : null}

          {showCompletedTasks && (
            completedTasks.length === 0 ? (
              <div className="text-center py-8 bg-[#1A1A1A] border border-white/5 rounded-xl">
                <p className="text-[#52525B] text-sm">No completed tasks yet</p>
              </div>
            ) : (
              completedTasks.map((task, i) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  variant="completed"
                  index={i}
                />
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
              Received ({incomingTransfersTotal})
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
              Sent ({outgoingTransfersTotal})
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
                role="button"
                tabIndex={0}
                onClick={() => navigate(`/lead/${t.lead_id}`)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    navigate(`/lead/${t.lead_id}`);
                  }
                }}
                className={`bg-[#1A1A1A] border rounded-xl p-4 cursor-pointer hover:bg-white/[0.02] transition-colors ${
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
                  <div className="flex items-center gap-2 flex-shrink-0" onClick={(e) => e.stopPropagation()}>
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-[#A1A1AA] hover:text-white h-8 w-8 p-0"
                      onClick={() => navigate(`/lead/${t.lead_id}`)}
                      data-testid={`view-transfer-lead-${t.id}`}
                      aria-label="View lead"
                    >
                      <Eye size={14} />
                    </Button>
                  </div>
                </div>
              </motion.div>
            ))
          )}
        </motion.div>
      )}

      <TaskDetailModal
        open={taskDetailOpen}
        onOpenChange={(open) => {
          setTaskDetailOpen(open);
          if (!open) setSelectedTask(null);
        }}
        task={selectedTask}
        onComplete={viewingAs ? undefined : handleCompleteFromModal}
        onOpenLead={handleOpenLeadFromTask}
        onEdit={viewingAs ? undefined : (task) => {
          setTaskDetailOpen(false);
          openTaskEdit(task);
        }}
      />

      <TaskEditModal
        open={taskEditOpen}
        onOpenChange={(open) => {
          setTaskEditOpen(open);
          if (!open) setEditingTask(null);
        }}
        task={editingTask}
        saving={savingTaskEdit}
        onSave={handleSaveTaskEdit}
      />

      <TaskCompleteModal
        open={taskCompleteOpen}
        onOpenChange={(open) => {
          setTaskCompleteOpen(open);
          if (!open) setSelectedTask(null);
        }}
        task={selectedTask}
        saving={completingTask}
        onConfirm={handleConfirmTaskComplete}
      />

      <LeadTasksDrawer
        open={leadTasksDrawerOpen}
        onOpenChange={(open) => {
          setLeadTasksDrawerOpen(open);
          if (!open) {
            setLeadTasksDrawerLead(null);
            setLeadTasksDrawerTasks([]);
            setLeadTasksDrawerHighlightId(null);
            setLeadTasksDrawerLoading(false);
          }
        }}
        lead={leadTasksDrawerLead}
        tasks={leadTasksDrawerTasks}
        loading={leadTasksDrawerLoading}
        highlightedTaskId={leadTasksDrawerHighlightId}
        onCompleteTask={viewingAs ? undefined : handleCompleteDrawerTask}
        onOpenLead={handleOpenDrawerLead}
      />

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
