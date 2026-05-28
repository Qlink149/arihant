import React, { useState, useEffect, useCallback, useRef } from 'react';
import { motion } from 'framer-motion';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { leadsAPI, tasksAPI } from '../services/api';
import { LeadDataTable } from '../components/leads/LeadDataTable';
import { buildPendingTaskMap } from '../utils/leadTable';
import { METRIC_LABELS } from '../utils/leadOverview';
import { isNurturingStatus, NURTURE_LABELS, NURTURING_STATUS } from '../utils/nurtureLabel';
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
  X,
  Plus,
  Copy,
  UserPlus,
  Users,
  CircleDot,
  Calendar
} from 'lucide-react';
import { Button } from '../components/ui/button';
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { Calendar as CalendarUI } from '../components/ui/calendar';

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

const emptyLeadFilters = () => ({
  budget: '',
  location: '',
  project: '',
  intent: '',
  vip: null,
  status: '',
  days: '',
  created_from: '',
  created_to: '',
  metric: '',
});

const filtersFromSearchParams = (searchParams) => ({
  ...emptyLeadFilters(),
  project: searchParams.get('project') || '',
  location: searchParams.get('location') || '',
  status: searchParams.get('status') || '',
  days: searchParams.get('days') || '',
  created_from: searchParams.get('created_from') || '',
  created_to: searchParams.get('created_to') || '',
  metric: searchParams.get('metric') || '',
});

const filtersToSearchParams = (filters, agentQuery) => {
  const params = new URLSearchParams();
  if (filters.project) params.set('project', filters.project);
  if (filters.location) params.set('location', filters.location);
  if (filters.status) params.set('status', filters.status);
  if (filters.days) params.set('days', String(filters.days));
  if (filters.created_from) params.set('created_from', filters.created_from);
  if (filters.created_to) params.set('created_to', filters.created_to);
  if (filters.metric) params.set('metric', filters.metric);
  const agent = (agentQuery || '').trim();
  if (agent) params.set('agent', agent);
  return params;
};

const VirtualCustomerPage = () => {
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
  const [duplicateGroups, setDuplicateGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState(() => searchParams.get('agent') || '');
  const [debouncedSearch, setDebouncedSearch] = useState(() => searchParams.get('agent') || '');
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [showAddCustomerModal, setShowAddCustomerModal] = useState(false);
  const [showDuplicates, setShowDuplicates] = useState(false);
  const [uploadingFile, setUploadingFile] = useState(false);
  const [submittingCustomer, setSubmittingCustomer] = useState(false);
  const [leadStatusTouched, setLeadStatusTouched] = useState(false);
  const [createNurtureLabel, setCreateNurtureLabel] = useState('');
  const [pendingTasks, setPendingTasks] = useState([]);
  const [pendingTaskMap, setPendingTaskMap] = useState(() => new Map());
  const [noteLeadId, setNoteLeadId] = useState(null);
  const [quickNote, setQuickNote] = useState('');
  const [savingQuickNote, setSavingQuickNote] = useState(false);

  // New customer form state
  const [newCustomer, setNewCustomer] = useState({
    first_name: '',
    last_name: '',
    phone: '',
    email: '',
    project: '',
    budget: '',
    reason_for_purchase: '',
    location: '',
    lead_source: '',
    presales_agent: '',
    presales_description: '',
    lead_status: '',
  });
  
  const [filters, setFilters] = useState(() => filtersFromSearchParams(searchParams));
  const [customDateRange, setCustomDateRange] = useState(null);
  const [dateMenuMode, setDateMenuMode] = useState('presets');
  const [dateDropdownOpen, setDateDropdownOpen] = useState(false);

  const budgetRanges = ['Under 1Cr', '1-2 Cr', '2-5 Cr', '5 Cr+'];
  const locations = ['ECR', 'Abhiramapuram', 'OMR', 'Saligramam', 'Kilpauk'];
  const projects = ['ECR - Reserve 16', 'Saligramam Melange', 'OMR - Vivriti', 'Abhiramapuram - Krishna', 'Flowers Road - Kilpauk'];
  const intents = ['Investor', 'Self-Occupation', 'Not Decided'];
  const leadSources = ['Facebook Lead Form', 'facebook_ad', 'google', 'website', 'instagram', 'whatsapp', 'newspaper', 'direct-walkin', 'propmart', 'management reference', 'CREDAI FAIRPRO 2026'];
  const salesManagers = ['Narendran S', 'Piyush', 'Malathy', 'Anusha Omprakash', 'jigar', 'shariff', 'Roshini'];
  const LEAD_STATUSES = [
    'New',
    'RNR',
    'Contacted',
    'Nurturing',
    'Site Visit Scheduled',
    'Visit Completed',
    'Negotiation',
    'Gone Cold',
    'Future Prospect',
    'Closed Won',
    'Closed Lost',
  ];

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
    setSearchQuery(agent);
  }, [searchParams]);

  useEffect(() => {
    if (showDuplicates) return;
    setSearchParams(filtersToSearchParams(filters, debouncedSearch), { replace: true });
  }, [filters, debouncedSearch, showDuplicates, setSearchParams]);

  const fetchPendingTasks = useCallback(async () => {
    try {
      const { data } = await tasksAPI.getAll({ status: 'pending', mine: true });
      const list = data || [];
      setPendingTasks(list);
      setPendingTaskMap(buildPendingTaskMap(list));
    } catch {
      /* non-blocking */
    }
  }, []);

  useEffect(() => {
    fetchPendingTasks();
  }, [fetchPendingTasks]);

  useEffect(() => {
    const delay = searchQuery.trim() ? 400 : 0;
    const t = setTimeout(() => setDebouncedSearch(searchQuery.trim()), delay);
    return () => clearTimeout(t);
  }, [searchQuery]);

  useEffect(() => {
    leadsLengthRef.current = leads.length;
  }, [leads.length]);

  const buildLeadQueryParams = useCallback((skip = 0) => {
    const params = { skip, limit: VC_PAGE };
    if (filters.budget) params.budget = filters.budget;
    if (filters.location) params.location = filters.location;
    if (filters.project) params.project = filters.project;
    if (filters.intent) params.intent = filters.intent;
    if (filters.vip !== null) params.vip = filters.vip;
    if (filters.status) params.status = filters.status;
    if (filters.days) {
      const d = parseInt(filters.days, 10);
      if (Number.isFinite(d) && d > 0) params.days = d;
    } else {
      if (filters.created_from) params.created_from = filters.created_from;
      if (filters.created_to) params.created_to = filters.created_to;
    }
    if (filters.metric) params.metric = filters.metric;
    if (debouncedSearch) params.search = debouncedSearch;
    return params;
  }, [filters, debouncedSearch]);

  const prefetchKey = () => JSON.stringify(buildLeadQueryParams(0));

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
    [buildLeadQueryParams]
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
  }, [loadingMore, hasMoreLeads, totalLeads, buildLeadQueryParams, prefetchNextVcPage]);

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

  useEffect(() => {
    if (showDuplicates || loading) return;
    const onScroll = () => {
      const { scrollTop, clientHeight, scrollHeight } = document.documentElement;
      if (scrollTop + clientHeight >= scrollHeight - 200) {
        appendLeadsPage();
      }
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, [showDuplicates, loading, appendLeadsPage]);

  const findDuplicates = useCallback(async () => {
    setLoading(true);
    try {
      const response = await leadsAPI.getAll({ skip: 0, limit: 5000 });
      const allLeads = response.data;
      
      // Group by normalized phone
      const phoneGroups = {};
      allLeads.forEach(lead => {
        if (lead.normalized_phone) {
          if (!phoneGroups[lead.normalized_phone]) {
            phoneGroups[lead.normalized_phone] = [];
          }
          phoneGroups[lead.normalized_phone].push(lead);
        }
      });
      
      // Filter only groups with more than 1 lead
      const duplicates = Object.values(phoneGroups).filter(group => group.length > 1);
      setDuplicateGroups(duplicates);
      setLeads([]);
    } catch (error) {
      console.error('Failed to find duplicates:', error);
      toast.error('Failed to find duplicates');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!showDuplicates) {
      resetAndFetchLeads();
    } else {
      findDuplicates();
    }
  }, [showDuplicates, resetAndFetchLeads, findDuplicates]);

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

  const handleSearch = (e) => {
    e.preventDefault();
    fetchLeads();
  };

  const clearFilters = () => {
    const empty = emptyLeadFilters();
    setFilters(empty);
    setCustomDateRange(null);
    setDateMenuMode('presets');
    setDateDropdownOpen(false);
    setSearchQuery('');
    setDebouncedSearch('');
    setShowDuplicates(false);
    setSearchParams(new URLSearchParams(), { replace: true });
  };

  const applyDatePreset = (preset) => {
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

  const handleViewLead = (id) => navigate(`/lead/${id}`);

  const handleOpenNote = (id) => {
    setNoteLeadId(id);
    setQuickNote('');
  };

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
      await fetchPendingTasks();
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
      toast.error('Failed to upload CSV');
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

    setSubmittingCustomer(true);
    try {
      const payload = { ...newCustomer };
      if (isNurturingStatus(newCustomer.lead_status)) {
        payload.temperature = createNurtureLabel;
      } else {
        delete payload.temperature;
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
      setNewCustomer({
        first_name: '',
        last_name: '',
        phone: '',
        email: '',
        project: '',
        budget: '',
        reason_for_purchase: '',
        location: '',
        lead_source: '',
        presales_agent: '',
        presales_description: '',
        lead_status: '',
      });
      setLeadStatusTouched(false);
      setCreateNurtureLabel('');
      fetchLeads();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to add customer');
    } finally {
      setSubmittingCustomer(false);
    }
  };

  const activeFiltersCount = Object.values(filters).filter(v => v !== '' && v !== null).length + (showDuplicates ? 1 : 0);

  return (
    <div className="space-y-6">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col lg:flex-row lg:items-center justify-between gap-4"
      >
        <div>
          <h1 className="font-serif text-3xl text-white" data-testid="virtual-customer-title">
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
          
          <Button
            onClick={() => setShowUploadModal(true)}
            className="bg-[#1A1A1A] border border-white/10 text-white hover:bg-white/5"
            data-testid="upload-csv-btn"
          >
            <Upload size={16} className="mr-2" />
            Upload CSV
          </Button>
        </div>
      </motion.div>

      {filters.metric ? (
        <div
          className="flex items-center gap-2 flex-wrap"
          data-testid="lead-overview-filter-chip"
        >
          <span className="inline-flex items-center gap-2 px-3 py-1.5 rounded-md border border-[#C5A059]/30 bg-[#C5A059]/10 text-[#C5A059] text-xs font-medium">
            Lead overview: {METRIC_LABELS[filters.metric] || filters.metric}
            <button
              type="button"
              onClick={() => setFilters((prev) => ({ ...prev, metric: '' }))}
              className="ml-1 text-[#C5A059]/80 hover:text-[#C5A059] underline-offset-2 hover:underline"
              aria-label="Clear lead overview filter"
            >
              Clear
            </button>
          </span>
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
          <form onSubmit={handleSearch} className="flex-1">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-[#52525B]" size={18} />
              <Input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search by name, email, or phone..."
                className="pl-10 bg-black/50 border-white/10 text-white placeholder:text-[#52525B] h-11"
                data-testid="search-input"
              />
            </div>
          </form>

          {/* Filter Dropdowns */}
          <div className="flex flex-wrap items-center gap-2">
            {/* Duplicate Filter */}
            <Button
              variant="outline"
              onClick={() => setShowDuplicates(!showDuplicates)}
              className={`bg-[#1A1A1A] border-white/10 text-white hover:bg-white/5 ${
                showDuplicates ? 'border-red-500 text-red-500' : ''
              }`}
              data-testid="duplicate-filter"
            >
              <Copy size={14} className="mr-2" />
              Duplicates
            </Button>

            {/* Budget Filter */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  className={`bg-[#1A1A1A] border-white/10 text-white hover:bg-white/5 ${
                    filters.budget ? 'border-[#C5A059] text-[#C5A059]' : ''
                  }`}
                  data-testid="budget-filter"
                >
                  <Filter size={14} className="mr-2" />
                  {filters.budget || 'Budget'}
                  <ChevronDown size={14} className="ml-2" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent className="bg-[#1A1A1A] border-white/10">
                <DropdownMenuLabel className="text-[#A1A1AA]">Budget Range</DropdownMenuLabel>
                <DropdownMenuSeparator className="bg-white/10" />
                {budgetRanges.map((range) => (
                  <DropdownMenuItem
                    key={range}
                    onClick={() => setFilters({ ...filters, budget: range })}
                    className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
                  >
                    {range}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Location Filter */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  className={`bg-[#1A1A1A] border-white/10 text-white hover:bg-white/5 ${
                    filters.location ? 'border-[#C5A059] text-[#C5A059]' : ''
                  }`}
                  data-testid="location-filter"
                >
                  <MapPin size={14} className="mr-2" />
                  {filters.location || 'Location'}
                  <ChevronDown size={14} className="ml-2" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent className="bg-[#1A1A1A] border-white/10">
                <DropdownMenuLabel className="text-[#A1A1AA]">Location</DropdownMenuLabel>
                <DropdownMenuSeparator className="bg-white/10" />
                {locations.map((loc) => (
                  <DropdownMenuItem
                    key={loc}
                    onClick={() => setFilters({ ...filters, location: loc })}
                    className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
                  >
                    {loc}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Project Filter */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  className={`bg-[#1A1A1A] border-white/10 text-white hover:bg-white/5 ${
                    filters.project ? 'border-[#C5A059] text-[#C5A059]' : ''
                  }`}
                  data-testid="project-filter"
                >
                  <Building size={14} className="mr-2" />
                  {filters.project || 'Project'}
                  <ChevronDown size={14} className="ml-2" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent className="bg-[#1A1A1A] border-white/10">
                <DropdownMenuLabel className="text-[#A1A1AA]">Project Interest</DropdownMenuLabel>
                <DropdownMenuSeparator className="bg-white/10" />
                {projects.map((proj) => (
                  <DropdownMenuItem
                    key={proj}
                    onClick={() => setFilters({ ...filters, project: proj })}
                    className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
                  >
                    {proj}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>

            {/* Status Filter */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  className={`bg-[#1A1A1A] border-white/10 text-white hover:bg-white/5 ${
                    filters.status ? 'border-[#C5A059] text-[#C5A059]' : ''
                  }`}
                  data-testid="status-filter"
                >
                  <CircleDot size={14} className="mr-2" />
                  {filters.status ? `Status: ${filters.status}` : 'Status'}
                  <ChevronDown size={14} className="ml-2" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent className="bg-[#1A1A1A] border-white/10 max-h-[min(24rem,70vh)] overflow-y-auto">
                <DropdownMenuLabel className="text-[#A1A1AA]">Lead Status</DropdownMenuLabel>
                <DropdownMenuSeparator className="bg-white/10" />
                <DropdownMenuItem
                  onClick={() => setFilters({ ...filters, status: '' })}
                  className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
                >
                  All Statuses
                </DropdownMenuItem>
                <DropdownMenuSeparator className="bg-white/10" />
                {LEAD_STATUSES.map((status) => (
                  <DropdownMenuItem
                    key={status}
                    onClick={() => setFilters({ ...filters, status })}
                    className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
                  >
                    {status}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>

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

            {/* VIP Filter */}
            <Button
              variant="outline"
              onClick={() => setFilters({ ...filters, vip: filters.vip === true ? null : true })}
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
                        <span className="inline-block mt-2 px-2 py-1 bg-green-500/20 text-green-400 text-xs rounded">
                          Primary
                        </span>
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
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.2 }}
          >
            <LeadDataTable
              leads={leads}
              loading={loading}
              pendingTaskMap={pendingTaskMap}
              pendingTasksList={pendingTasks}
              onRowClick={handleViewLead}
              onView={handleViewLead}
              onNote={handleOpenNote}
            />
          </motion.div>
          {!loading && leads.length > 0 && (
            <>
              <div ref={loadMoreSentinelRef} className="h-1 w-full" aria-hidden />
              {loadingMore && (
                <p className="text-center text-[#52525B] text-sm py-3 w-full">Loading more leads…</p>
              )}
            </>
          )}
        </>
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

      {/* Add New Customer Modal */}
      <Dialog open={showAddCustomerModal} onOpenChange={setShowAddCustomerModal}>
        <DialogContent className="bg-[#1A1A1A] border-white/10 text-white max-w-2xl max-h-[90vh] overflow-y-auto">
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
                <label className="text-[#A1A1AA] text-sm mb-2 block">Email Address</label>
                <Input
                  type="email"
                  value={newCustomer.email}
                  onChange={(e) => setNewCustomer({ ...newCustomer, email: e.target.value })}
                  placeholder="email@example.com"
                  className="bg-black/50 border-white/10 text-white"
                />
              </div>
            </div>

            {/* Project & Budget Row */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-[#A1A1AA] text-sm mb-2 block">Interested Project</label>
                <Select
                  value={newCustomer.project}
                  onValueChange={(value) => setNewCustomer({ ...newCustomer, project: value })}
                >
                  <SelectTrigger className="bg-black/50 border-white/10 text-white">
                    <SelectValue placeholder="Select Project" />
                  </SelectTrigger>
                  <SelectContent className="bg-[#1A1A1A] border-white/10">
                    {projects.map((proj) => (
                      <SelectItem key={proj} value={proj} className="text-white hover:bg-[#C5A059]/10">
                        {proj}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-[#A1A1AA] text-sm mb-2 block">Budget Alignment</label>
                <Select
                  value={newCustomer.budget}
                  onValueChange={(value) => setNewCustomer({ ...newCustomer, budget: value })}
                >
                  <SelectTrigger className="bg-black/50 border-white/10 text-white">
                    <SelectValue placeholder="Select Budget" />
                  </SelectTrigger>
                  <SelectContent className="bg-[#1A1A1A] border-white/10">
                    {budgetRanges.map((range) => (
                      <SelectItem key={range} value={range} className="text-white hover:bg-[#C5A059]/10">
                        {range}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Intent & Location Row */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-[#A1A1AA] text-sm mb-2 block">Intent Type</label>
                <Select
                  value={newCustomer.reason_for_purchase}
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
                <Select
                  value={newCustomer.location}
                  onValueChange={(value) => setNewCustomer({ ...newCustomer, location: value })}
                >
                  <SelectTrigger className="bg-black/50 border-white/10 text-white">
                    <SelectValue placeholder="Select Location" />
                  </SelectTrigger>
                  <SelectContent className="bg-[#1A1A1A] border-white/10">
                    {locations.map((loc) => (
                      <SelectItem key={loc} value={loc} className="text-white hover:bg-[#C5A059]/10">
                        {loc}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Source & Manager Row */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-[#A1A1AA] text-sm mb-2 block">Lead Source</label>
                <Select
                  value={newCustomer.lead_source}
                  onValueChange={(value) => setNewCustomer({ ...newCustomer, lead_source: value })}
                >
                  <SelectTrigger className="bg-black/50 border-white/10 text-white">
                    <SelectValue placeholder="Select Source" />
                  </SelectTrigger>
                  <SelectContent className="bg-[#1A1A1A] border-white/10">
                    {leadSources.map((source) => (
                      <SelectItem key={source} value={source} className="text-white hover:bg-[#C5A059]/10">
                        {source}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-[#A1A1AA] text-sm mb-2 block">Assigned Sales Manager</label>
                <Select
                  value={newCustomer.presales_agent}
                  onValueChange={(value) => setNewCustomer({ ...newCustomer, presales_agent: value })}
                >
                  <SelectTrigger className="bg-black/50 border-white/10 text-white">
                    <SelectValue placeholder="Select Manager" />
                  </SelectTrigger>
                  <SelectContent className="bg-[#1A1A1A] border-white/10">
                    {salesManagers.map((manager) => (
                      <SelectItem key={manager} value={manager} className="text-white hover:bg-[#C5A059]/10">
                        {manager}
                      </SelectItem>
                    ))}
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
