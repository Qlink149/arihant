import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { motion } from 'framer-motion';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { leadsAPI, tasksAPI, usersAPI } from '../services/api';
import { useAuth } from '../context/AuthContext';
import { LeadListSearchInput } from '../components/leads/LeadListSearchInput';
import { LeadListTable } from '../components/leads/LeadListTable';
import { LeadExportModal } from '../components/leads/LeadExportModal';
import { MultiSelectFilterDropdown } from '../components/leads/MultiSelectFilterDropdown';
import { LeadFilterViewsBar } from '../components/leads/LeadFilterViewsBar';
import {
  applyViewFiltersToState,
  buildLeadListParams,
  countActiveFilters,
  emptyLeadFilters,
  filtersFromSearchParams,
  filtersToSearchParams,
  snapshotFiltersForView,
} from '../utils/leadFilters';
import { buildEarliestPendingTaskMap, buildPendingTaskMap } from '../utils/leadTable';
import { LeadTasksDrawer } from '../components/tasks/LeadTasksDrawer';
import { METRIC_LABELS } from '../utils/leadOverview';
import { isNurturingStatus, NURTURE_LABELS, NURTURING_STATUS } from '../utils/nurtureLabel';
import { UI_LEAD_STATUSES as LEAD_STATUSES } from '../constants/leadStatus';
import { toast } from 'sonner';
import {
  Search,
  Filter,
  ChevronDown,
  Crown,
  User,
  Building,
  MapPin,
  Phone,
  Mail,
  Upload,
  Download,
  X,
  Plus,
  Copy,
  UserPlus,
  Users,
  CircleDot,
  Calendar
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { CrmBadge } from '../components/ui/CrmBadge';
import { Input } from '../components/ui/input';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
  DropdownMenuLabel
} from '../components/ui/dropdown-menu';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../components/ui/dialog';
import { SelectWithOther } from '../components/ui/SelectWithOther';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { isOtherModeWithEmptyText } from '../utils/selectWithOther';
import { TABLE_DENSITY_STORAGE_KEY } from '../constants/performanceFlags';
import { Calendar as CalendarUI } from '../components/ui/calendar';
import {
  BUDGET_RANGES,
  CANONICAL_LOCATIONS,
  CANONICAL_PROJECTS,
  CANONICAL_SOURCES,
  mergePicklistWithApi,
  picklistNames,
} from '../constants/leadPicklists';

const VC_PAGE = 50;

const formatLocalDate = (date) => {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
};

const addDays = (date, delta) => {
  const next = new Date(date);
  next.setDate(next.getDate() + delta);
  return next;
};

const parseYmd = (value) => {
  if (!value) return null;
  const [y, m, d] = value.split('-').map(Number);
  if (!y || !m || !d) return null;
  return new Date(y, m - 1, d);
};

const getDateFilterLabel = (filters) => {
  if (filters.days) {
    const n = parseInt(filters.days, 10);
    if (Number.isFinite(n) && n > 0) return `Last ${n} days`;
  }
  if (filters.created_from || filters.created_to) {
    const from = filters.created_from || '…';
    const to = filters.created_to || '…';
    if (from === to) return from;
    return `${from} – ${to}`;
  }
  return 'Date';
};

const isDateFilterActive = (filters) =>
  Boolean(filters.days || filters.created_from || filters.created_to);

const getMetaQualifiedLabel = (filters) => {
  if (filters.meta_qualified === true) return 'Meta: Yes';
  if (filters.meta_qualified === false) return 'Meta: No';
  return 'Meta Qualified';
};

const EMPTY_NEW_CUSTOMER = {
  first_name: '',
  last_name: '',
  phone: '',
  work_phone: '',
  email: '',
  project: '',
  budget: '',
  reason_for_purchase: '',
  location: '',
  lead_source: '',
  original_source: '',
  most_recent_source: '',
  unit_size: '',
  site_visit_count: 0,
  meta_qualified: null,
  presales_agent: '',
  assigned_user_id: '',
  presales_description: '',
  lead_status: '',
};

const parseTotalFromResponse = (response) => {
  const headers = response?.headers;
  if (!headers) return null;
  let raw = headers['x-total-count'] ?? headers['X-Total-Count'];
  if (raw == null && typeof headers === 'object') {
    const key = Object.keys(headers).find((k) => k.toLowerCase() === 'x-total-count');
    if (key) raw = headers[key];
  }
  const n = parseInt(raw, 10);
  return Number.isFinite(n) ? n : null;
};

const VirtualCustomerPage = () => {
  const { user } = useAuth();
  const isAdmin = (user?.role || '').toLowerCase() === 'admin';
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [leads, setLeads] = useState([]);
  const [totalLeads, setTotalLeads] = useState(0);
  const [hasMoreLeads, setHasMoreLeads] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const loadMoreSentinelRef = useRef(null);
  const prefetchedBuffer = useRef([]);
  const prefetchedKey = useRef('');
  const leadsLengthRef = useRef(0);
  const leadsFetchBusy = useRef(false);
  const leadsFetchGeneration = useRef(0);
  const lastFetchedLeadsKey = useRef('');
  const prevShowDuplicates = useRef(false);
  const [duplicateGroups, setDuplicateGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchInputValue, setSearchInputValue] = useState(() => searchParams.get('agent') || '');
  const [debouncedSearch, setDebouncedSearch] = useState(() => searchParams.get('agent') || '');
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);
  const [showAddCustomerModal, setShowAddCustomerModal] = useState(false);
  const [showDuplicates, setShowDuplicates] = useState(false);
  const [tableDensity, setTableDensity] = useState(() => {
    try {
      return localStorage.getItem(TABLE_DENSITY_STORAGE_KEY) === 'compact' ? 'compact' : 'comfortable';
    } catch {
      return 'comfortable';
    }
  });
  const [uploadingFile, setUploadingFile] = useState(false);
  const [submittingCustomer, setSubmittingCustomer] = useState(false);
  const [leadStatusTouched, setLeadStatusTouched] = useState(false);
  const [createNurtureLabel, setCreateNurtureLabel] = useState('');
  const [pendingTasks, setPendingTasks] = useState([]);
  const [leadTasksDrawerOpen, setLeadTasksDrawerOpen] = useState(false);
  const [leadTasksDrawerLead, setLeadTasksDrawerLead] = useState(null);
  const [leadTasksDrawerTasks, setLeadTasksDrawerTasks] = useState([]);
  const [leadTasksDrawerLoading, setLeadTasksDrawerLoading] = useState(false);
  const [leadTasksDrawerHighlightId, setLeadTasksDrawerHighlightId] = useState(null);
  const [noteLeadId, setNoteLeadId] = useState(null);
  const [quickNote, setQuickNote] = useState('');
  const [savingQuickNote, setSavingQuickNote] = useState(false);

  const [newCustomer, setNewCustomer] = useState({ ...EMPTY_NEW_CUSTOMER });
  
  const [filters, setFilters] = useState(() => filtersFromSearchParams(searchParams));
  const [customDateRange, setCustomDateRange] = useState(null);
  const [dateMenuMode, setDateMenuMode] = useState('presets');
  const [dateDropdownOpen, setDateDropdownOpen] = useState(false);

  const [locationOptions, setLocationOptions] = useState([]);
  const [projectOptions, setProjectOptions] = useState([]);
  const [sourceOptions, setSourceOptions] = useState([]);
  const [filterOptionsLoading, setFilterOptionsLoading] = useState(true);
  const [filterViews, setFilterViews] = useState([]);
  const [filterViewsLoading, setFilterViewsLoading] = useState(true);
  const [activeFilterViewId, setActiveFilterViewId] = useState(null);
  const [assigneeOptions, setAssigneeOptions] = useState([]);
  const [assigneesLoading, setAssigneesLoading] = useState(true);
  const [addCustomerFieldModes, setAddCustomerFieldModes] = useState({
    project: 'preset',
    budget: 'preset',
    location: 'preset',
    lead_source: 'preset',
  });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [filterRes, assigneeRes, viewsRes] = await Promise.all([
          leadsAPI.getFilterOptions(),
          usersAPI.listAssignees(),
          leadsAPI.getFilterViews(),
        ]);
        if (cancelled) return;
        const filterData = filterRes?.data;
        setLocationOptions(mergePicklistWithApi(CANONICAL_LOCATIONS, filterData?.locations || []));
        setProjectOptions(mergePicklistWithApi(CANONICAL_PROJECTS, filterData?.projects || []));
        setSourceOptions(mergePicklistWithApi(CANONICAL_SOURCES, filterData?.sources || []));
        setAssigneeOptions(Array.isArray(assigneeRes?.data) ? assigneeRes.data : []);
        setFilterViews(Array.isArray(viewsRes?.data) ? viewsRes.data : []);
      } catch {
        if (!cancelled) {
          setLocationOptions(mergePicklistWithApi(CANONICAL_LOCATIONS, []));
          setProjectOptions(mergePicklistWithApi(CANONICAL_PROJECTS, []));
          setSourceOptions(mergePicklistWithApi(CANONICAL_SOURCES, []));
          setAssigneeOptions([]);
          setFilterViews([]);
        }
      } finally {
        if (!cancelled) {
          setFilterOptionsLoading(false);
          setAssigneesLoading(false);
          setFilterViewsLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (filters.created_from || filters.created_to) {
      const from = parseYmd(filters.created_from);
      const to = parseYmd(filters.created_to) || from;
      if (from) setCustomDateRange({ from, to: to || from });
    } else {
      setCustomDateRange(null);
    }
  }, [filters.created_from, filters.created_to]);

  useEffect(() => {
    const fromUrl = filtersFromSearchParams(searchParams);
    setFilters((prev) => {
      const prevKey = JSON.stringify(prev);
      const nextKey = JSON.stringify(fromUrl);
      return prevKey === nextKey ? prev : fromUrl;
    });
    const agent = searchParams.get('agent') || '';
    setSearchInputValue(agent);
    setDebouncedSearch(agent);
  }, [searchParams]);

  const handleDebouncedSearchChange = useCallback((value) => {
    setDebouncedSearch(value);
  }, []);

  useEffect(() => {
    if (showDuplicates) return;
    setSearchParams(filtersToSearchParams(filters, debouncedSearch), { replace: true });
  }, [filters, debouncedSearch, showDuplicates, setSearchParams]);

  const fetchPendingTasks = useCallback(async () => {
    try {
      const { data } = await tasksAPI.getAll({ status: 'pending', mine: true });
      setPendingTasks(data || []);
    } catch {
      /* non-blocking */
    }
  }, []);

  const fetchLeadPendingTasks = useCallback(async (leadId) => {
    if (!leadId) return [];
    const { data } = await tasksAPI.getAll({ status: 'pending', lead_id: leadId, mine: true });
    return Array.isArray(data) ? data : [];
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
        // stable sort by due_date then created_at, so the list feels deterministic
        const sorted = [...list].sort((a, b) => {
          const ad = String(a?.due_date || '');
          const bd = String(b?.due_date || '');
          if (ad !== bd) return ad.localeCompare(bd);
          return String(b?.created_at || '').localeCompare(String(a?.created_at || ''));
        });
        setLeadTasksDrawerTasks(sorted);
      } catch (error) {
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
        // Refresh both the drawer list and the summary map
        if (leadId) {
          setLeadTasksDrawerLoading(true);
          const list = await fetchLeadPendingTasks(leadId);
          setLeadTasksDrawerTasks(list);
          setLeadTasksDrawerLoading(false);
        }
        await fetchPendingTasks();
      } catch {
        toast.error('Failed to update task');
      }
    },
    [leadTasksDrawerLead?.id, fetchLeadPendingTasks, fetchPendingTasks]
  );

  const handleOpenDrawerLead = useCallback(
    (leadId) => {
      if (!leadId) return;
      setLeadTasksDrawerOpen(false);
      navigate(`/lead/${leadId}`);
    },
    [navigate]
  );

  useEffect(() => {
    fetchPendingTasks();
  }, [fetchPendingTasks]);

  const pendingTaskMap = useMemo(() => buildPendingTaskMap(pendingTasks), [pendingTasks]);
  const earliestTaskMap = useMemo(
    () => buildEarliestPendingTaskMap(pendingTasks),
    [pendingTasks]
  );

  useEffect(() => {
    leadsLengthRef.current = leads.length;
  }, [leads.length]);

  const buildLeadQueryParams = useCallback((skip = 0) => {
    return { skip, limit: VC_PAGE, ...buildLeadListParams(filters, debouncedSearch) };
  }, [filters, debouncedSearch]);

  const exportParams = useMemo(
    () => buildLeadListParams(filters, debouncedSearch),
    [filters, debouncedSearch],
  );

  const prefetchKey = useCallback(
    () => JSON.stringify(buildLeadQueryParams(0)),
    [buildLeadQueryParams]
  );

  const prefetchNextVcPage = useCallback(
    (skip) => {
      const k = `${prefetchKey()}:${skip}`;
      if (prefetchedKey.current === k && prefetchedBuffer.current.length) return;
      leadsAPI
        .getAll(buildLeadQueryParams(skip))
        .then((response) => {
          const batch = response.data || [];
          prefetchedKey.current = k;
          prefetchedBuffer.current = batch;
          const total = parseTotalFromResponse(response);
          if (total !== null) {
            setTotalLeads((prev) => (prev > 0 ? prev : total));
          }
        })
        .catch(() => {});
    },
    [buildLeadQueryParams, prefetchKey]
  );

  const resetAndFetchLeads = useCallback(async () => {
    leadsFetchGeneration.current += 1;
    const requestGen = leadsFetchGeneration.current;

    setLoading(true);
    setHasMoreLeads(true);
    setTotalLeads(0);
    prefetchedBuffer.current = [];
    prefetchedKey.current = '';
    leadsFetchBusy.current = false;
    try {
      const params = buildLeadQueryParams(0);
      const response = await leadsAPI.getAll(params);
      if (requestGen !== leadsFetchGeneration.current) return;

      const batch = response.data || [];
      const total = parseTotalFromResponse(response);
      if (total !== null) setTotalLeads(total);
      setLeads(batch);
      setHasMoreLeads(batch.length === VC_PAGE);
      if (batch.length === VC_PAGE) {
        prefetchNextVcPage(VC_PAGE);
      }
    } catch (error) {
      if (requestGen !== leadsFetchGeneration.current) return;
      console.error('Failed to fetch leads:', error);
      toast.error('Failed to load leads');
    } finally {
      if (requestGen === leadsFetchGeneration.current) {
        setLoading(false);
      }
    }
  }, [buildLeadQueryParams, prefetchNextVcPage]);

  const appendLeadsPage = useCallback(async () => {
    if (leadsFetchBusy.current || loadingMore || !hasMoreLeads) return;
    if (totalLeads > 0 && leadsLengthRef.current >= totalLeads) {
      setHasMoreLeads(false);
      return;
    }
    const requestGen = leadsFetchGeneration.current;
    const skip = leadsLengthRef.current;
    const k = `${prefetchKey()}:${skip}`;
    leadsFetchBusy.current = true;
    setLoadingMore(true);
    try {
      let batch = [];
      let response = null;
      if (prefetchedKey.current === k && prefetchedBuffer.current.length) {
        batch = prefetchedBuffer.current;
        prefetchedBuffer.current = [];
      } else {
        response = await leadsAPI.getAll(buildLeadQueryParams(skip));
        if (requestGen !== leadsFetchGeneration.current) return;
        batch = response.data || [];
        const total = parseTotalFromResponse(response);
        if (total !== null) setTotalLeads(total);
      }
      if (requestGen !== leadsFetchGeneration.current) return;

      if (!batch.length) {
        setHasMoreLeads(false);
        return;
      }
      setLeads((prev) => {
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
      setHasMoreLeads(batch.length === VC_PAGE);
      if (batch.length === VC_PAGE) {
        prefetchNextVcPage(skip + batch.length);
      }
    } catch (error) {
      if (requestGen !== leadsFetchGeneration.current) return;
      console.error('Failed to load more leads:', error);
    } finally {
      if (requestGen === leadsFetchGeneration.current) {
        setLoadingMore(false);
      }
      leadsFetchBusy.current = false;
    }
  }, [loadingMore, hasMoreLeads, totalLeads, buildLeadQueryParams, prefetchNextVcPage, prefetchKey]);

  useEffect(() => {
    const el = loadMoreSentinelRef.current;
    if (!el || showDuplicates || loading) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) appendLeadsPage();
      },
      { root: null, rootMargin: '200px', threshold: 0 }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [showDuplicates, loading, leads.length, hasMoreLeads, appendLeadsPage]);

  const findDuplicates = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await leadsAPI.getDuplicateGroups({ skip: 0, limit: 100 });
      setDuplicateGroups(data?.groups || []);
      setLeads([]);
    } catch (error) {
      console.error('Failed to find duplicates:', error);
      toast.error('Failed to find duplicates');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (showDuplicates) {
      findDuplicates();
      prevShowDuplicates.current = true;
      return;
    }

    const key = prefetchKey();
    const exitedDuplicateMode = prevShowDuplicates.current;
    prevShowDuplicates.current = false;

    if (!exitedDuplicateMode && key === lastFetchedLeadsKey.current) {
      return;
    }
    lastFetchedLeadsKey.current = key;
    resetAndFetchLeads();
  }, [showDuplicates, prefetchKey, resetAndFetchLeads, findDuplicates]);

  const fetchLeads = async () => {
    await resetAndFetchLeads();
  };

  const handleMergeLeads = async (primaryId, duplicateId) => {
    try {
      await leadsAPI.merge(primaryId, duplicateId);
      toast.success('Leads merged successfully');
      findDuplicates();
    } catch (error) {
      toast.error('Failed to merge leads');
    }
  };

  const clearFilters = () => {
    const empty = emptyLeadFilters();
    setFilters(empty);
    setActiveFilterViewId(null);
    setCustomDateRange(null);
    setDateMenuMode('presets');
    setDateDropdownOpen(false);
    setSearchInputValue('');
    setDebouncedSearch('');
    setShowDuplicates(false);
    setSearchParams(new URLSearchParams(), { replace: true });
  };

  const applyFilterView = useCallback((view) => {
    if (!view?.filters) return;
    const { filters: nextFilters, search } = applyViewFiltersToState(view.filters);
    setFilters(nextFilters);
    setSearchInputValue(search);
    setDebouncedSearch(search);
    setActiveFilterViewId(view.id);
    setShowDuplicates(false);
  }, []);

  const handleSaveFilterView = useCallback(
    async (name) => {
      const payload = {
        name,
        filters: snapshotFiltersForView(filters, debouncedSearch),
      };
      const { data } = await leadsAPI.createFilterView(payload);
      setFilterViews((prev) => [...prev, data].sort((a, b) => a.name.localeCompare(b.name)));
      setActiveFilterViewId(data.id);
      return data;
    },
    [filters, debouncedSearch]
  );

  const handleUpdateFilterView = useCallback(
    async (viewId, { name } = {}) => {
      const payload = name
        ? { name, filters: snapshotFiltersForView(filters, debouncedSearch) }
        : { filters: snapshotFiltersForView(filters, debouncedSearch) };
      const { data } = await leadsAPI.updateFilterView(viewId, payload);
      setFilterViews((prev) =>
        prev
          .map((v) => (v.id === viewId ? data : v))
          .sort((a, b) => a.name.localeCompare(b.name))
      );
      return data;
    },
    [filters, debouncedSearch]
  );

  const handleDeleteFilterView = useCallback(async (viewId) => {
    await leadsAPI.deleteFilterView(viewId);
    setFilterViews((prev) => prev.filter((v) => v.id !== viewId));
    setActiveFilterViewId((prev) => (prev === viewId ? null : prev));
  }, []);

  const applyDatePreset = (preset) => {
    setActiveFilterViewId(null);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const clearDateFields = { days: '', created_from: '', created_to: '' };

    setDateMenuMode('presets');

    if (preset === 'all') {
      setCustomDateRange(null);
      setFilters((prev) => ({ ...prev, ...clearDateFields }));
      return;
    }

    setCustomDateRange(null);

    if (['7', '30', '60', '90'].includes(preset)) {
      setFilters((prev) => ({ ...prev, ...clearDateFields, days: preset }));
      return;
    }

    let target = today;
    if (preset === 'yesterday') target = addDays(today, -1);
    if (preset === 'day_before') target = addDays(today, -2);
    const ymd = formatLocalDate(target);
    setFilters((prev) => ({ ...prev, ...clearDateFields, created_from: ymd, created_to: ymd }));
  };

  const handleCustomRangeSelect = (range) => {
    setActiveFilterViewId(null);
    setCustomDateRange(range);
    if (!range?.from) return;

    const from = formatLocalDate(range.from);
    const to = range.to ? formatLocalDate(range.to) : from;
    setFilters((prev) => ({
      ...prev,
      days: '',
      created_from: from,
      created_to: to,
    }));

    if (range.to) {
      setDateMenuMode('presets');
      setDateDropdownOpen(false);
    }
  };

  const handleViewLead = useCallback((id) => navigate(`/lead/${id}`), [navigate]);

  const handleOpenNote = useCallback((id) => {
    setNoteLeadId(id);
    setQuickNote('');
  }, []);

  const handleBudgetsChange = useCallback((budgets) => {
    setActiveFilterViewId(null);
    setFilters((prev) => ({ ...prev, budgets }));
  }, []);

  const handleLocationsChange = useCallback((locations) => {
    setActiveFilterViewId(null);
    setFilters((prev) => ({ ...prev, locations }));
  }, []);

  const handleProjectsChange = useCallback((projects) => {
    setActiveFilterViewId(null);
    setFilters((prev) => ({ ...prev, projects }));
  }, []);

  const handleSourcesChange = useCallback((sources) => {
    setActiveFilterViewId(null);
    setFilters((prev) => ({ ...prev, sources }));
  }, []);

  const handleStatusesChange = useCallback((statuses) => {
    setActiveFilterViewId(null);
    setFilters((prev) => ({ ...prev, statuses }));
  }, []);

  const handleSaveQuickNote = async () => {
    if (!noteLeadId || !quickNote.trim()) {
      toast.error('Please enter a note');
      return;
    }
    setSavingQuickNote(true);
    try {
      await leadsAPI.addContext(noteLeadId, {
        note: quickNote.trim(),
        update_type: 'general_note',
      });
      toast.success('Note added');
      setNoteLeadId(null);
      setQuickNote('');
      await Promise.all([fetchLeads(), fetchPendingTasks()]);
    } catch {
      toast.error('Failed to save note');
    } finally {
      setSavingQuickNote(false);
    }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    setUploadingFile(true);
    try {
      const result = await leadsAPI.uploadCSV(file);
      toast.success(`Imported ${result.data.imported} leads. ${result.data.duplicates} duplicates skipped.`);
      setShowUploadModal(false);
      fetchLeads();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to upload CSV');
    } finally {
      setUploadingFile(false);
    }
  };

  const handleAddCustomer = async (e) => {
    e.preventDefault();
    
    if (!newCustomer.first_name || !newCustomer.phone) {
      toast.error('Please fill in required fields (Name and Phone)');
      return;
    }

    if (isNurturingStatus(newCustomer.lead_status) && !createNurtureLabel) {
      toast.error('Select a nurture label (Hot or Warm) for Nurturing leads');
      return;
    }

    const otherFieldChecks = [
      { key: 'project', label: 'Interested Project', mode: addCustomerFieldModes.project },
      { key: 'budget', label: 'Budget', mode: addCustomerFieldModes.budget },
      { key: 'location', label: 'Location', mode: addCustomerFieldModes.location },
      { key: 'lead_source', label: 'Lead Source', mode: addCustomerFieldModes.lead_source },
    ];
    for (const field of otherFieldChecks) {
      if (isOtherModeWithEmptyText(field.mode, newCustomer[field.key])) {
        toast.error(`Please enter a custom value for ${field.label}`);
        return;
      }
    }

    setSubmittingCustomer(true);
    try {
      const payload = { ...newCustomer };
      if (payload.meta_qualified === 'yes') payload.meta_qualified = true;
      else if (payload.meta_qualified === 'no') payload.meta_qualified = false;
      else if (payload.meta_qualified === 'unset' || payload.meta_qualified === '') payload.meta_qualified = null;
      const svCount = parseInt(payload.site_visit_count, 10);
      payload.site_visit_count = Number.isFinite(svCount) && svCount >= 0 ? svCount : 0;
      if (isNurturingStatus(newCustomer.lead_status)) {
        payload.temperature = createNurtureLabel;
      } else {
        delete payload.temperature;
      }
      if (payload.assigned_user_id) {
        const assignee = assigneeOptions.find((a) => String(a.id) === String(payload.assigned_user_id));
        if (assignee?.full_name) {
          payload.presales_agent = assignee.full_name;
          payload.assigned_to_name = assignee.full_name;
        }
      } else {
        delete payload.assigned_user_id;
        delete payload.assigned_to_name;
        if (!payload.presales_agent) delete payload.presales_agent;
      }
      const created = await leadsAPI.create(payload);
      const createdLeadId = created?.data?.id;
      const shouldAppendStatusNote = leadStatusTouched && !!createdLeadId && !!newCustomer.lead_status;

      if (shouldAppendStatusNote) {
        const description = `Status set to ${newCustomer.lead_status}`.slice(0, 500);
        await leadsAPI.addContext(createdLeadId, {
          type: 'note',
          description,
          timestamp: new Date().toISOString(),
        });
      }

      toast.success('Customer added successfully!');
      setShowAddCustomerModal(false);
      setNewCustomer({ ...EMPTY_NEW_CUSTOMER });
      setLeadStatusTouched(false);
      setCreateNurtureLabel('');
      setAddCustomerFieldModes({ project: 'preset', budget: 'preset', location: 'preset', lead_source: 'preset' });
      fetchLeads();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to add customer');
    } finally {
      setSubmittingCustomer(false);
    }
  };

  const activeFiltersCount = countActiveFilters(filters, { includeDuplicates: showDuplicates });

  return (
    <div className="space-y-3">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col lg:flex-row lg:items-center justify-between gap-4"
      >
        <div>
          <h1 className="text-xl font-semibold text-white" data-testid="virtual-customer-title">
            Virtual Customer Explorer
          </h1>
          <motion.div className="mt-1" data-testid="virtual-customer-lead-count" role="status">
            {showDuplicates ? (
              <p className="text-[#A1A1AA]">
                {duplicateGroups.length} duplicate groups found
              </p>
            ) : loading ? (
              <p className="text-[#A1A1AA]">Loading leads…</p>
            ) : totalLeads > 0 ? (
              <>
                <p className="text-[#A1A1AA]">
                  {totalLeads} leads
                  {activeFiltersCount > 0 ? ' match your filters' : ''}
                </p>
                {leads.length < totalLeads && (
                  <p className="text-[#52525B] text-sm mt-0.5">
                    {leads.length} loaded — scroll for more
                  </p>
                )}
              </>
            ) : leads.length === 0 ? (
              <p className="text-[#A1A1AA]">No leads found</p>
            ) : (
              <p className="text-[#A1A1AA]">Loading count…</p>
            )}
          </motion.div>
        </div>

        <div className="flex items-center gap-3">
          {/* Add New Customer Button */}
          <Button
            onClick={() => setShowAddCustomerModal(true)}
            className="bg-[#C5A059] text-black hover:bg-[#E5C079]"
            data-testid="add-customer-btn"
          >
            <UserPlus size={16} className="mr-2" />
            Add New Customer
          </Button>
          
          {isAdmin && !showDuplicates && (
            <Button
              onClick={() => setShowExportModal(true)}
              className="bg-[#1A1A1A] border border-white/10 text-white hover:bg-white/5"
              data-testid="export-csv-btn"
            >
              <Download size={16} className="mr-2" />
              Export CSV
            </Button>
          )}
          {isAdmin && (
            <Button
              onClick={() => setShowUploadModal(true)}
              className="bg-[#1A1A1A] border border-white/10 text-white hover:bg-white/5"
              data-testid="upload-csv-btn"
            >
              <Upload size={16} className="mr-2" />
              Upload CSV
            </Button>
          )}
        </div>
      </motion.div>

      {(filters.metric || filters.dormant) ? (
        <div
          className="flex items-center gap-2 flex-wrap"
          data-testid="lead-overview-filter-chip"
        >
          {filters.metric ? (
            <CrmBadge chip variant="gold" className="gap-2">
              Lead overview: {METRIC_LABELS[filters.metric] || filters.metric}
              <button
                type="button"
                onClick={() => setFilters((prev) => ({ ...prev, metric: '' }))}
                className="ml-1 opacity-80 hover:opacity-100 underline-offset-2 hover:underline"
                aria-label="Clear lead overview filter"
              >
                Clear
              </button>
            </CrmBadge>
          ) : null}
          {filters.dormant ? (
            <CrmBadge chip variant="warning" className="gap-2">
              {METRIC_LABELS.dormant || 'Dormant leads'}
              <button
                type="button"
                onClick={() => setFilters((prev) => ({ ...prev, dormant: false }))}
                className="ml-1 opacity-80 hover:opacity-100 underline-offset-2 hover:underline"
                aria-label="Clear dormant filter"
              >
                Clear
              </button>
            </CrmBadge>
          ) : null}
        </div>
      ) : null}

      {/* Search & Filters Bar */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="glass-card rounded-lg p-4"
      >
        <div className="flex flex-col lg:flex-row gap-4">
          {/* Search */}
          <LeadListSearchInput
            value={searchInputValue}
            onDebouncedChange={handleDebouncedSearchChange}
            onSubmit={fetchLeads}
          />

          {/* Filter Dropdowns */}
          <div className="flex flex-wrap items-center gap-2">
            {/* Duplicate Filter */}
            <Button
              variant="outline"
              onClick={() => {
                if (!showDuplicates) {
                  const ok = window.confirm(
                    'Finding duplicates loads up to 5,000 leads and may take a while on large databases. Continue?'
                  );
                  if (!ok) return;
                }
                setShowDuplicates(!showDuplicates);
              }}
              className={`bg-[#1A1A1A] border-white/10 text-white hover:bg-white/5 ${
                showDuplicates ? 'border-red-500 text-red-500' : ''
              }`}
              data-testid="duplicate-filter"
            >
              <Copy size={14} className="mr-2" />
              Duplicates
            </Button>

            {/* Budget Filter */}
            <MultiSelectFilterDropdown
              label="Budget"
              icon={Filter}
              options={BUDGET_RANGES}
              selected={filters.budgets}
              onChange={handleBudgetsChange}
              testId="budget-filter"
            />

            {/* Location Filter */}
            <MultiSelectFilterDropdown
              label="Location"
              icon={MapPin}
              options={locationOptions}
              selected={filters.locations}
              loading={filterOptionsLoading}
              onChange={handleLocationsChange}
              testId="location-filter"
            />

            {/* Project Filter */}
            <MultiSelectFilterDropdown
              label="Project"
              icon={Building}
              options={projectOptions}
              selected={filters.projects}
              loading={filterOptionsLoading}
              onChange={handleProjectsChange}
              testId="project-filter"
            />

            {/* Source Filter */}
            <MultiSelectFilterDropdown
              label="Source"
              icon={Filter}
              options={sourceOptions}
              selected={filters.sources}
              loading={filterOptionsLoading}
              onChange={handleSourcesChange}
              testId="source-filter"
            />

            {/* Status Filter */}
            <MultiSelectFilterDropdown
              label="Status"
              icon={CircleDot}
              options={LEAD_STATUSES}
              selected={filters.statuses}
              onChange={handleStatusesChange}
              testId="status-filter"
            />

            {/* Date Filter */}
            <DropdownMenu
              open={dateDropdownOpen}
              onOpenChange={(open) => {
                setDateDropdownOpen(open);
                if (!open) setDateMenuMode('presets');
              }}
            >
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  className={`bg-[#1A1A1A] border-white/10 text-white hover:bg-white/5 ${
                    isDateFilterActive(filters) ? 'border-[#C5A059] text-[#C5A059]' : ''
                  }`}
                  data-testid="date-filter"
                >
                  <Calendar size={14} className="mr-2" />
                  {getDateFilterLabel(filters)}
                  <ChevronDown size={14} className="ml-2" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                className="bg-[#1A1A1A] border-white/10"
                align="start"
                data-testid="date-filter-menu"
              >
                {dateMenuMode === 'presets' ? (
                  <>
                    <DropdownMenuLabel className="text-[#A1A1AA]">Created date</DropdownMenuLabel>
                    <DropdownMenuSeparator className="bg-white/10" />
                    <DropdownMenuItem
                      onClick={() => applyDatePreset('today')}
                      className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
                    >
                      Today
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={() => applyDatePreset('yesterday')}
                      className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
                    >
                      Yesterday
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={() => applyDatePreset('day_before')}
                      className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
                    >
                      Day before yesterday
                    </DropdownMenuItem>
                    <DropdownMenuSeparator className="bg-white/10" />
                    {[7, 30, 60, 90].map((n) => (
                      <DropdownMenuItem
                        key={n}
                        onClick={() => applyDatePreset(String(n))}
                        className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
                      >
                        Last {n} days
                      </DropdownMenuItem>
                    ))}
                    <DropdownMenuSeparator className="bg-white/10" />
                    <DropdownMenuItem
                      onSelect={(e) => {
                        e.preventDefault();
                        setDateMenuMode('custom');
                      }}
                      className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
                      data-testid="date-filter-custom"
                    >
                      Custom range
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      onClick={() => applyDatePreset('all')}
                      className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
                    >
                      All time
                    </DropdownMenuItem>
                  </>
                ) : (
                  <>
                    <DropdownMenuItem
                      onSelect={(e) => {
                        e.preventDefault();
                        setDateMenuMode('presets');
                      }}
                      className="text-[#A1A1AA] hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
                    >
                      ← Back to presets
                    </DropdownMenuItem>
                    <DropdownMenuSeparator className="bg-white/10" />
                    <DropdownMenuItem
                      className="p-0 focus:bg-transparent cursor-default"
                      onSelect={(e) => e.preventDefault()}
                      onPointerDown={(e) => e.preventDefault()}
                    >
                      <CalendarUI
                        mode="range"
                        selected={customDateRange}
                        onSelect={handleCustomRangeSelect}
                        className="bg-[#1A1A1A] text-white"
                        data-testid="date-range-calendar"
                      />
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Meta Qualified Filter */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  className={`bg-[#1A1A1A] border-white/10 text-white hover:bg-white/5 ${
                    filters.meta_qualified === true || filters.meta_qualified === false
                      ? 'border-[#C5A059] text-[#C5A059]'
                      : ''
                  }`}
                  data-testid="meta-qualified-filter"
                >
                  {getMetaQualifiedLabel(filters)}
                  <ChevronDown size={14} className="ml-2" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent className="bg-[#1A1A1A] border-white/10">
                <DropdownMenuItem
                  onClick={() => {
                    setActiveFilterViewId(null);
                    setFilters((prev) => ({ ...prev, meta_qualified: null }));
                  }}
                  className="text-white hover:bg-[#C5A059]/10 cursor-pointer"
                >
                  Any
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => {
                    setActiveFilterViewId(null);
                    setFilters((prev) => ({ ...prev, meta_qualified: true }));
                  }}
                  className="text-white hover:bg-[#C5A059]/10 cursor-pointer"
                >
                  Yes
                </DropdownMenuItem>
                <DropdownMenuItem
                  onClick={() => {
                    setActiveFilterViewId(null);
                    setFilters((prev) => ({ ...prev, meta_qualified: false }));
                  }}
                  className="text-white hover:bg-[#C5A059]/10 cursor-pointer"
                >
                  No
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>

            {/* VIP Filter */}
            <Button
              variant="outline"
              onClick={() => {
                setActiveFilterViewId(null);
                setFilters({ ...filters, vip: filters.vip === true ? null : true });
              }}
              className={`bg-[#1A1A1A] border-white/10 text-white hover:bg-white/5 ${
                filters.vip === true ? 'border-[#C5A059] text-[#C5A059]' : ''
              }`}
              data-testid="vip-filter"
            >
              <Crown size={14} className="mr-2" />
              VIP / HNI
            </Button>

            {/* Clear Filters */}
            {activeFiltersCount > 0 && (
              <Button
                variant="ghost"
                onClick={clearFilters}
                className="text-[#A1A1AA] hover:text-white"
                data-testid="clear-filters-btn"
              >
                <X size={14} className="mr-1" />
                Clear ({activeFiltersCount})
              </Button>
            )}
          </div>
        </div>

        <LeadFilterViewsBar
          views={filterViews}
          loading={filterViewsLoading}
          currentFilters={filters}
          currentSearch={debouncedSearch}
          activeViewId={activeFilterViewId}
          onApplyView={applyFilterView}
          onSaveView={handleSaveFilterView}
          onUpdateView={handleUpdateFilterView}
          onDeleteView={handleDeleteFilterView}
          onClearActiveView={() => setActiveFilterViewId(null)}
        />
      </motion.div>

      {/* Duplicate Groups View */}
      {showDuplicates && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="space-y-4"
        >
          {duplicateGroups.length === 0 ? (
            <div className="glass-card rounded-lg p-12 text-center">
              <Copy className="mx-auto text-[#52525B]" size={48} />
              <p className="text-[#A1A1AA] mt-4">No duplicate leads found</p>
              <p className="text-[#52525B] text-sm">All phone numbers are unique</p>
            </div>
          ) : (
            duplicateGroups.map((group, idx) => (
              <div key={idx} className="glass-card rounded-lg p-4">
                <div className="flex items-center gap-2 mb-4">
                  <Copy className="text-red-500" size={18} />
                  <span className="text-red-500 font-medium">
                    {group.length} leads with same phone: {group[0].normalized_phone}
                  </span>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {group.map((lead, lidx) => (
                    <div key={lead.id} className="p-4 bg-black/30 rounded-lg">
                      <div className="flex items-center gap-3 mb-2">
                        <div className="w-10 h-10 rounded-full bg-[#C5A059]/20 flex items-center justify-center text-[#C5A059] text-sm">
                          {lead.first_name?.charAt(0)}{lead.last_name?.charAt(0)}
                        </div>
                        <div>
                          <p className="text-white font-medium">{lead.first_name} {lead.last_name}</p>
                          <p className="text-[#52525B] text-xs">{lead.project}</p>
                        </div>
                      </div>
                      <p className="text-[#A1A1AA] text-sm">{lead.phone}</p>
                      <p className="text-[#52525B] text-xs mt-1">Source: {lead.lead_source}</p>
                      {lidx === 0 ? (
                        <CrmBadge variant="success" className="mt-2">
                          Primary
                        </CrmBadge>
                      ) : (
                        <Button
                          size="sm"
                          onClick={() => handleMergeLeads(group[0].id, lead.id)}
                          className="mt-2 bg-red-500/20 text-red-400 hover:bg-red-500/30"
                        >
                          Merge into Primary
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}
        </motion.div>
      )}

      {/* Lead table */}
      {!showDuplicates && (
        <LeadListTable
          leads={leads}
          loading={loading}
          loadingMore={loadingMore}
          pendingTaskMap={pendingTaskMap}
          earliestTaskMap={earliestTaskMap}
          tableDensity={tableDensity}
          onTableDensityChange={setTableDensity}
          onRowClick={handleViewLead}
          onNote={handleOpenNote}
          onOpenLeadTasks={openLeadTasksDrawer}
          loadMoreSentinelRef={loadMoreSentinelRef}
        />
      )}

      {/* Quick note modal */}
      <Dialog open={!!noteLeadId} onOpenChange={(open) => !open && setNoteLeadId(null)}>
        <DialogContent className="bg-[#1A1A1A] border-white/10 text-white max-w-lg" data-testid="quick-note-modal">
          <DialogHeader>
            <DialogTitle className="font-serif text-xl">Add note</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 mt-2">
            <textarea
              value={quickNote}
              onChange={(e) => setQuickNote(e.target.value)}
              placeholder="Write a note for this lead..."
              rows={4}
              className="w-full px-3 py-2 bg-black/50 border border-white/10 rounded-lg text-white text-sm placeholder:text-[#52525B] focus:border-[#C5A059]/50 focus:outline-none resize-none"
              data-testid="quick-note-input"
            />
            <div className="flex justify-end gap-2">
              <Button
                variant="ghost"
                onClick={() => setNoteLeadId(null)}
                className="text-[#A1A1AA]"
              >
                Cancel
              </Button>
              <Button
                onClick={handleSaveQuickNote}
                disabled={savingQuickNote || !quickNote.trim()}
                className="bg-[#C5A059] text-black hover:bg-[#E5C079]"
                data-testid="quick-note-save"
              >
                {savingQuickNote ? 'Saving…' : 'Save note'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

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
        onCompleteTask={handleCompleteDrawerTask}
        onOpenLead={handleOpenDrawerLead}
      />

      {/* Add New Customer Modal */}
      <Dialog open={showAddCustomerModal} onOpenChange={setShowAddCustomerModal}>
        <DialogContent
          className="bg-[#1A1A1A] border-white/10 text-white max-w-2xl max-h-[90vh] overflow-y-auto"
          aria-describedby={undefined}
        >
          <DialogHeader>
            <DialogTitle className="font-serif text-xl flex items-center gap-2">
              <UserPlus className="text-[#C5A059]" size={24} />
              Add New Customer
            </DialogTitle>
          </DialogHeader>
          <form onSubmit={handleAddCustomer} className="space-y-4">
            {/* Name Row */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-[#A1A1AA] text-sm mb-2 block">First Name *</label>
                <Input
                  value={newCustomer.first_name}
                  onChange={(e) => setNewCustomer({ ...newCustomer, first_name: e.target.value })}
                  placeholder="First Name"
                  className="bg-black/50 border-white/10 text-white"
                  required
                />
              </div>
              <div>
                <label className="text-[#A1A1AA] text-sm mb-2 block">Last Name</label>
                <Input
                  value={newCustomer.last_name}
                  onChange={(e) => setNewCustomer({ ...newCustomer, last_name: e.target.value })}
                  placeholder="Last Name"
                  className="bg-black/50 border-white/10 text-white"
                />
              </div>
            </div>

            {/* Contact Row */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-[#A1A1AA] text-sm mb-2 block">Mobile Number *</label>
                <Input
                  value={newCustomer.phone}
                  onChange={(e) => setNewCustomer({ ...newCustomer, phone: e.target.value })}
                  placeholder="+91 XXXXX XXXXX"
                  className="bg-black/50 border-white/10 text-white"
                  required
                />
              </div>
              <div>
                <label className="text-[#A1A1AA] text-sm mb-2 block">Work (alternate number)</label>
                <Input
                  value={newCustomer.work_phone}
                  onChange={(e) => setNewCustomer({ ...newCustomer, work_phone: e.target.value })}
                  placeholder="Alternate phone"
                  className="bg-black/50 border-white/10 text-white"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-[#A1A1AA] text-sm mb-2 block">Email Address</label>
                <Input
                  type="email"
                  value={newCustomer.email}
                  onChange={(e) => setNewCustomer({ ...newCustomer, email: e.target.value })}
                  placeholder="email@example.com"
                  className="bg-black/50 border-white/10 text-white"
                />
              </div>
              <div>
                <label className="text-[#A1A1AA] text-sm mb-2 block">Unit Size</label>
                <Input
                  value={newCustomer.unit_size}
                  onChange={(e) => setNewCustomer({ ...newCustomer, unit_size: e.target.value })}
                  placeholder="e.g. 3 BHK"
                  className="bg-black/50 border-white/10 text-white"
                />
              </div>
            </div>

            {/* Project & Budget Row */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-[#A1A1AA] text-sm mb-2 block">Interested Project</label>
                <SelectWithOther
                  value={newCustomer.project}
                  onChange={(value) => setNewCustomer({ ...newCustomer, project: value })}
                  onModeChange={(mode) =>
                    setAddCustomerFieldModes((prev) => ({ ...prev, project: mode }))
                  }
                  options={picklistNames(projectOptions)}
                  placeholder="Select Project"
                  otherPlaceholder="Enter project name"
                  loading={filterOptionsLoading}
                  loadingLabel="Loading projects…"
                  otherInputTestId="add-customer-project-other"
                />
              </div>
              <div>
                <label className="text-[#A1A1AA] text-sm mb-2 block">Budget Alignment</label>
                <SelectWithOther
                  value={newCustomer.budget}
                  onChange={(value) => setNewCustomer({ ...newCustomer, budget: value })}
                  onModeChange={(mode) =>
                    setAddCustomerFieldModes((prev) => ({ ...prev, budget: mode }))
                  }
                  options={BUDGET_RANGES}
                  placeholder="Select Budget"
                  otherPlaceholder="Enter budget range"
                  otherInputTestId="add-customer-budget-other"
                />
              </div>
            </div>

            {/* Intent & Location Row */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-[#A1A1AA] text-sm mb-2 block">Intent Type</label>
                <Select
                  value={newCustomer.reason_for_purchase || undefined}
                  onValueChange={(value) => setNewCustomer({ ...newCustomer, reason_for_purchase: value })}
                >
                  <SelectTrigger className="bg-black/50 border-white/10 text-white">
                    <SelectValue placeholder="Select Intent" />
                  </SelectTrigger>
                  <SelectContent className="bg-[#1A1A1A] border-white/10">
                    <SelectItem value="Investor" className="text-white hover:bg-[#C5A059]/10">Investor</SelectItem>
                    <SelectItem value="Self-Occupation" className="text-white hover:bg-[#C5A059]/10">Self-Occupation</SelectItem>
                    <SelectItem value="Not Decided" className="text-white hover:bg-[#C5A059]/10">Not Decided</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-[#A1A1AA] text-sm mb-2 block">Location Preference</label>
                <SelectWithOther
                  value={newCustomer.location}
                  onChange={(value) => setNewCustomer({ ...newCustomer, location: value })}
                  onModeChange={(mode) =>
                    setAddCustomerFieldModes((prev) => ({ ...prev, location: mode }))
                  }
                  options={picklistNames(locationOptions)}
                  placeholder="Select Location"
                  otherPlaceholder="Enter location"
                  loading={filterOptionsLoading}
                  loadingLabel="Loading locations…"
                  otherInputTestId="add-customer-location-other"
                />
              </div>
            </div>

            {/* Source & Manager Row */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-[#A1A1AA] text-sm mb-2 block">Lead Source</label>
                <SelectWithOther
                  value={newCustomer.lead_source}
                  onChange={(value) => setNewCustomer({ ...newCustomer, lead_source: value })}
                  onModeChange={(mode) =>
                    setAddCustomerFieldModes((prev) => ({ ...prev, lead_source: mode }))
                  }
                  options={picklistNames(sourceOptions)}
                  placeholder="Select Source"
                  otherPlaceholder="Enter source"
                  loading={filterOptionsLoading}
                  loadingLabel="Loading sources…"
                  otherInputTestId="add-customer-source-other"
                />
              </div>
              <div>
                <label className="text-[#A1A1AA] text-sm mb-2 block">Assigned Sales Manager</label>
                <Select
                  value={newCustomer.assigned_user_id ? String(newCustomer.assigned_user_id) : '__unassigned__'}
                  onValueChange={(value) => {
                    if (value === '__unassigned__') {
                      setNewCustomer({
                        ...newCustomer,
                        assigned_user_id: '',
                        presales_agent: '',
                      });
                      return;
                    }
                    const assignee = assigneeOptions.find((a) => String(a.id) === value);
                    setNewCustomer({
                      ...newCustomer,
                      assigned_user_id: value,
                      presales_agent: assignee?.full_name || '',
                    });
                  }}
                >
                  <SelectTrigger className="bg-black/50 border-white/10 text-white">
                    <SelectValue placeholder="Select Manager" />
                  </SelectTrigger>
                  <SelectContent className="bg-[#1A1A1A] border-white/10 max-h-60 overflow-y-auto">
                    <SelectItem value="__unassigned__" className="text-white hover:bg-[#C5A059]/10">
                      Unassigned
                    </SelectItem>
                    {assigneesLoading ? (
                      <SelectItem value="__loading_mgr" disabled className="text-[#52525B]">
                        Loading managers…
                      </SelectItem>
                    ) : (
                      assigneeOptions.map((user) => (
                        <SelectItem
                          key={user.id}
                          value={String(user.id)}
                          className="text-white hover:bg-[#C5A059]/10"
                        >
                          {user.full_name}
                          {user.role ? ` (${user.role})` : ''}
                        </SelectItem>
                      ))
                    )}
                  </SelectContent>
                </Select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-[#A1A1AA] text-sm mb-2 block">Original source</label>
                <Input
                  value={newCustomer.original_source}
                  onChange={(e) => setNewCustomer({ ...newCustomer, original_source: e.target.value })}
                  placeholder="Original source"
                  className="bg-black/50 border-white/10 text-white"
                />
              </div>
              <div>
                <label className="text-[#A1A1AA] text-sm mb-2 block">Most recent source</label>
                <Input
                  value={newCustomer.most_recent_source}
                  onChange={(e) => setNewCustomer({ ...newCustomer, most_recent_source: e.target.value })}
                  placeholder="Most recent source"
                  className="bg-black/50 border-white/10 text-white"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-[#A1A1AA] text-sm mb-2 block">No. of Site Visits</label>
                <Input
                  type="number"
                  min={0}
                  value={newCustomer.site_visit_count}
                  onChange={(e) => setNewCustomer({ ...newCustomer, site_visit_count: e.target.value })}
                  className="bg-black/50 border-white/10 text-white"
                />
              </div>
              <div>
                <label className="text-[#A1A1AA] text-sm mb-2 block">Meta Qualified</label>
                <Select
                  value={
                    newCustomer.meta_qualified === true
                      ? 'yes'
                      : newCustomer.meta_qualified === false
                        ? 'no'
                        : 'unset'
                  }
                  onValueChange={(value) =>
                    setNewCustomer({
                      ...newCustomer,
                      meta_qualified: value === 'yes' ? true : value === 'no' ? false : null,
                    })
                  }
                >
                  <SelectTrigger className="bg-black/50 border-white/10 text-white">
                    <SelectValue placeholder="Not set" />
                  </SelectTrigger>
                  <SelectContent className="bg-[#1A1A1A] border-white/10">
                    <SelectItem value="unset" className="text-white hover:bg-[#C5A059]/10">Not set</SelectItem>
                    <SelectItem value="yes" className="text-white hover:bg-[#C5A059]/10">Yes</SelectItem>
                    <SelectItem value="no" className="text-white hover:bg-[#C5A059]/10">No</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Timeline */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-[#A1A1AA] text-sm block">Timeline</label>
                <span className="text-[#52525B] text-xs">Optional</span>
              </div>

              <div className="relative">
                <div className="absolute left-0 right-0 top-1/2 -translate-y-1/2 h-[2px] bg-white/10" />
                {(() => {
                  const idx = LEAD_STATUSES.indexOf(newCustomer.lead_status);
                  const pct = idx >= 0 ? (idx / (LEAD_STATUSES.length - 1)) * 100 : 0;
                  return (
                    <div
                      className="absolute left-0 top-1/2 -translate-y-1/2 h-[2px] bg-[#C5A059] transition-all"
                      style={{ width: `${pct}%` }}
                    />
                  );
                })()}

                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2 relative">
                  {LEAD_STATUSES.map((status) => {
                    const isSelected = newCustomer.lead_status === status;
                    return (
                      <button
                        key={status}
                        type="button"
                        onClick={() => {
                          setNewCustomer({ ...newCustomer, lead_status: status });
                          setLeadStatusTouched(true);
                          if (status !== NURTURING_STATUS) {
                            setCreateNurtureLabel('');
                          }
                        }}
                        className={[
                          'group flex flex-col items-center gap-2 p-2 rounded-md transition-colors',
                          'hover:bg-white/5 focus:outline-none focus:ring-2 focus:ring-[#C5A059]/40',
                        ].join(' ')}
                        aria-current={isSelected ? 'step' : undefined}
                      >
                        <div
                          className={[
                            'h-3 w-3 rounded-full border transition-colors',
                            isSelected
                              ? 'bg-[#C5A059] border-[#C5A059]'
                              : 'bg-[#0B0B0B] border-white/20 group-hover:border-[#C5A059]/60',
                          ].join(' ')}
                        />
                        <span
                          className={[
                            'text-[11px] leading-tight text-center',
                            isSelected ? 'text-white' : 'text-[#A1A1AA] group-hover:text-white/80',
                          ].join(' ')}
                        >
                          {status}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {isNurturingStatus(newCustomer.lead_status) && (
                <div className="mt-4 p-4 rounded-lg border border-[#C5A059]/30 bg-[#C5A059]/5">
                  <label className="text-[#C5A059] text-sm font-medium block mb-2">
                    Nurture label <span className="text-red-400">*</span>
                  </label>
                  <div className="flex gap-4">
                    {NURTURE_LABELS.map((label) => (
                      <label key={label} className="flex items-center gap-2 cursor-pointer text-white text-sm">
                        <input
                          type="radio"
                          name="create-nurture-label"
                          value={label}
                          checked={createNurtureLabel === label}
                          onChange={() => setCreateNurtureLabel(label)}
                          className="accent-[#C5A059]"
                        />
                        {label}
                      </label>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Notes */}
            <div>
              <label className="text-[#A1A1AA] text-sm mb-2 block">Additional Notes</label>
              <textarea
                value={newCustomer.presales_description}
                onChange={(e) => setNewCustomer({ ...newCustomer, presales_description: e.target.value })}
                placeholder="Any additional information about the customer..."
                className="w-full h-24 px-4 py-3 bg-black/50 border border-white/10 rounded-md text-white placeholder:text-[#52525B] resize-none"
              />
            </div>

            {/* Submit Button */}
            <div className="flex gap-3 pt-4">
              <Button
                type="button"
                variant="outline"
                onClick={() => setShowAddCustomerModal(false)}
                className="flex-1 border-white/10 text-white hover:bg-white/5"
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={submittingCustomer}
                className="flex-1 bg-[#C5A059] text-black hover:bg-[#E5C079] disabled:opacity-50"
              >
                {submittingCustomer ? 'Adding...' : 'Add Customer'}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <LeadExportModal
        open={showExportModal}
        onOpenChange={setShowExportModal}
        totalLeads={totalLeads}
        activeFiltersCount={activeFiltersCount}
        exportParams={exportParams}
      />

      {/* Upload CSV Modal */}
      <Dialog open={showUploadModal} onOpenChange={setShowUploadModal}>
        <DialogContent className="bg-[#1A1A1A] border-white/10 text-white">
          <DialogHeader>
            <DialogTitle className="font-serif text-xl">Upload Lead CSV</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <p className="text-[#A1A1AA] text-sm">
              Upload a CSV file with lead data. The system will automatically detect and skip duplicates.
            </p>
            <div className="border-2 border-dashed border-white/20 rounded-lg p-8 text-center hover:border-[#C5A059]/50 transition-colors">
              <input
                type="file"
                accept=".csv"
                onChange={handleFileUpload}
                className="hidden"
                id="csv-upload"
                data-testid="csv-file-input"
              />
              <label htmlFor="csv-upload" className="cursor-pointer">
                <Upload className="mx-auto text-[#A1A1AA]" size={32} />
                <p className="text-[#A1A1AA] mt-2">
                  {uploadingFile ? 'Uploading...' : 'Click to select CSV file'}
                </p>
              </label>
            </div>
            <div className="text-[#52525B] text-xs">
              <p className="font-medium mb-1">Supported CSV column formats:</p>
              <p><strong>Format 1:</strong> ID, First name, Last name, Created at, Mobile, Email IDs, Project, Sales owner, Status, Source, Recent note</p>
              <p className="mt-1"><strong>Format 2:</strong> First Name, Last Name, Phone, Email, Project, Lead Status, Lead Source, Budget, Location, Presales Agent, Presales Description</p>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default VirtualCustomerPage;
