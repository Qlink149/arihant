import React, { useState, useEffect, useCallback, useRef } from 'react';
import { motion } from 'framer-motion';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { leadsAPI } from '../services/api';
import { toast } from 'sonner';
import {
  Search,
  Filter,
  ChevronDown,
  Flame,
  Snowflake,
  Sun,
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
  Users
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

const VC_PAGE = 50;

const VirtualCustomerPage = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [leads, setLeads] = useState([]);
  const [hasMoreLeads, setHasMoreLeads] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const loadMoreSentinelRef = useRef(null);
  const prefetchedBuffer = useRef([]);
  const prefetchedKey = useRef('');
  const leadsLengthRef = useRef(0);
  const [duplicateGroups, setDuplicateGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [showAddCustomerModal, setShowAddCustomerModal] = useState(false);
  const [showDuplicates, setShowDuplicates] = useState(false);
  const [uploadingFile, setUploadingFile] = useState(false);
  const [submittingCustomer, setSubmittingCustomer] = useState(false);
  const [leadStatusTouched, setLeadStatusTouched] = useState(false);
  
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
  
  // Filters
  const [filters, setFilters] = useState({
    budget: '',
    location: '',
    project: '',
    temperature: '',
    intent: '',
    vip: null
  });

  const budgetRanges = ['Under 1Cr', '1-2 Cr', '2-5 Cr', '5 Cr+'];
  const locations = ['ECR', 'Abhiramapuram', 'OMR', 'Saligramam', 'Kilpauk'];
  const projects = ['ECR - Reserve 16', 'Saligramam Melange', 'OMR - Vivriti', 'Abhiramapuram - Krishna', 'Flowers Road - Kilpauk'];
  const temperatures = ['Hot', 'Warm', 'Cold'];
  const intents = ['Investor', 'Self-Occupation', 'Not Decided'];
  const leadSources = ['Facebook Lead Form', 'facebook_ad', 'google', 'website', 'instagram', 'whatsapp', 'newspaper', 'direct-walkin', 'propmart', 'management reference', 'CREDAI FAIRPRO 2026'];
  const salesManagers = ['Narendran S', 'Piyush', 'Malathy', 'Anusha Omprakash', 'jigar', 'shariff', 'Roshini'];
  const LEAD_STATUSES = ['Open', 'Contacted', 'Follow Up', 'Site Visit', 'Lost', 'Won'];

  // Check URL params for initial filters
  useEffect(() => {
    const projectParam = searchParams.get('project');
    const locationParam = searchParams.get('location');
    const agentParam = searchParams.get('agent');
    
    if (projectParam || locationParam || agentParam) {
      setFilters(prev => ({
        ...prev,
        project: projectParam || '',
        location: locationParam || ''
      }));
      if (agentParam) {
        setSearchQuery(agentParam);
      }
    }
  }, [searchParams]);

  useEffect(() => {
    leadsLengthRef.current = leads.length;
  }, [leads.length]);

  const buildLeadQueryParams = useCallback((skip = 0) => {
    const params = { skip, limit: VC_PAGE };
    if (filters.budget) params.budget = filters.budget;
    if (filters.location) params.location = filters.location;
    if (filters.project) params.project = filters.project;
    if (filters.temperature) params.temperature = filters.temperature;
    if (filters.intent) params.intent = filters.intent;
    if (filters.vip !== null) params.vip = filters.vip;
    if (searchQuery) params.search = searchQuery;
    return params;
  }, [filters, searchQuery]);

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
        })
        .catch(() => {});
    },
    [buildLeadQueryParams]
  );

  const resetAndFetchLeads = useCallback(async () => {
    setLoading(true);
    setHasMoreLeads(true);
    prefetchedBuffer.current = [];
    prefetchedKey.current = '';
    try {
      const params = buildLeadQueryParams(0);
      const response = await leadsAPI.getAll(params);
      const batch = response.data || [];
      setLeads(batch);
      setHasMoreLeads(batch.length === VC_PAGE);
      if (batch.length === VC_PAGE) {
        prefetchNextVcPage(VC_PAGE);
      }
    } catch (error) {
      console.error('Failed to fetch leads:', error);
      toast.error('Failed to load leads');
    } finally {
      setLoading(false);
    }
  }, [buildLeadQueryParams, prefetchNextVcPage]);

  const appendLeadsPage = useCallback(async () => {
    if (loadingMore || !hasMoreLeads) return;
    const skip = leadsLengthRef.current;
    const k = `${prefetchKey()}:${skip}`;
    setLoadingMore(true);
    try {
      let batch = [];
      if (prefetchedKey.current === k && prefetchedBuffer.current.length) {
        batch = prefetchedBuffer.current;
        prefetchedBuffer.current = [];
      } else {
        const response = await leadsAPI.getAll(buildLeadQueryParams(skip));
        batch = response.data || [];
      }
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
      console.error('Failed to load more leads:', error);
    } finally {
      setLoadingMore(false);
    }
  }, [loadingMore, hasMoreLeads, buildLeadQueryParams, prefetchNextVcPage]);

  useEffect(() => {
    const el = loadMoreSentinelRef.current;
    if (!el || showDuplicates) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) appendLeadsPage();
      },
      { root: null, rootMargin: '200px', threshold: 0 }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [showDuplicates, appendLeadsPage]);

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
    setFilters({
      budget: '',
      location: '',
      project: '',
      temperature: '',
      intent: '',
      vip: null
    });
    setSearchQuery('');
    setShowDuplicates(false);
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

    setSubmittingCustomer(true);
    try {
      const created = await leadsAPI.create(newCustomer);
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
      fetchLeads();
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Failed to add customer');
    } finally {
      setSubmittingCustomer(false);
    }
  };

  const getTemperatureIcon = (temp) => {
    switch (temp) {
      case 'Hot':
        return <Flame className="text-red-500" size={14} />;
      case 'Warm':
        return <Sun className="text-orange-500" size={14} />;
      case 'Cold':
        return <Snowflake className="text-blue-500" size={14} />;
      default:
        return null;
    }
  };

  const getTemperatureBadge = (temp) => {
    const classes = {
      Hot: 'badge-hot',
      Warm: 'badge-warm',
      Cold: 'badge-cold'
    };
    return classes[temp] || 'bg-gray-500';
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
          <p className="text-[#A1A1AA] mt-1">
            {showDuplicates 
              ? `${duplicateGroups.length} duplicate groups found` 
              : `${leads.length} leads found`
            }
          </p>
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

            {/* Temperature Filter */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  className={`bg-[#1A1A1A] border-white/10 text-white hover:bg-white/5 ${
                    filters.temperature ? 'border-[#C5A059] text-[#C5A059]' : ''
                  }`}
                  data-testid="temperature-filter"
                >
                  {getTemperatureIcon(filters.temperature) || <Flame size={14} className="mr-2 text-[#52525B]" />}
                  <span className="ml-2">{filters.temperature || 'Temperature'}</span>
                  <ChevronDown size={14} className="ml-2" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent className="bg-[#1A1A1A] border-white/10">
                <DropdownMenuLabel className="text-[#A1A1AA]">Lead Temperature</DropdownMenuLabel>
                <DropdownMenuSeparator className="bg-white/10" />
                {temperatures.map((temp) => (
                  <DropdownMenuItem
                    key={temp}
                    onClick={() => setFilters({ ...filters, temperature: temp })}
                    className="text-white hover:bg-[#C5A059]/10 hover:text-[#C5A059] cursor-pointer"
                  >
                    <span className="flex items-center gap-2">
                      {getTemperatureIcon(temp)}
                      {temp}
                    </span>
                  </DropdownMenuItem>
                ))}
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

      {/* Lead Cards Grid */}
      {!showDuplicates && (
        <>
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.2 }}
          className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"
        >
          {loading ? (
            [...Array(6)].map((_, i) => (
              <div key={i} className="glass-card rounded-lg p-6 animate-pulse">
                <div className="flex items-center gap-4">
                  <div className="w-14 h-14 rounded-full bg-white/10" />
                  <div className="flex-1">
                    <div className="h-4 bg-white/10 rounded w-3/4" />
                    <div className="h-3 bg-white/10 rounded w-1/2 mt-2" />
                  </div>
                </div>
              </div>
            ))
          ) : leads.length === 0 ? (
            <div className="col-span-full text-center py-12">
              <User className="mx-auto text-[#52525B]" size={48} />
              <p className="text-[#A1A1AA] mt-4">No leads found</p>
              <p className="text-[#52525B] text-sm">Try adjusting your filters</p>
            </div>
          ) : (
            leads.map((lead, index) => (
              <motion.div
                key={lead.id}
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.05 }}
                onClick={() => navigate(`/lead/${lead.id}`)}
                className="glass-card rounded-lg p-6 cursor-pointer card-hover group"
                data-testid={`lead-card-${lead.id}`}
              >
                {/* Project Badge at Top */}
                {lead.project && (
                  <div className="flex items-center gap-2 mb-3 pb-3 border-b border-white/10">
                    <Building className="text-[#C5A059]" size={14} />
                    <span className="text-[#C5A059] text-sm font-medium">{lead.project}</span>
                  </div>
                )}
                
                <div className="flex items-start gap-4">
                  {/* Avatar */}
                  <div className="w-14 h-14 rounded-full bg-[#C5A059]/20 flex items-center justify-center text-[#C5A059] font-serif text-xl flex-shrink-0 group-hover:bg-[#C5A059]/30 transition-colors">
                    {lead.first_name?.charAt(0)}{lead.last_name?.charAt(0)}
                  </div>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="font-medium text-white truncate group-hover:text-[#C5A059] transition-colors">
                        {lead.first_name} {lead.last_name}
                      </h3>
                      {lead.vip && (
                        <Crown className="text-purple-500 flex-shrink-0" size={14} />
                      )}
                    </div>
                    
                    {/* Assigned Sales Manager */}
                    {lead.assigned_to && (
                      <p className="text-[#52525B] text-xs mt-1">
                        Assigned to: <span className="text-[#A1A1AA]">{lead.assigned_to}</span>
                      </p>
                    )}

                    {/* Badges */}
                    <div className="flex items-center gap-2 mt-3">
                      <span className={`px-2 py-1 rounded text-xs font-medium ${getTemperatureBadge(lead.temperature)}`}>
                        {lead.temperature}
                      </span>
                      <span className="px-2 py-1 rounded text-xs bg-white/10 text-[#A1A1AA]">
                        {lead.intent}
                      </span>
                    </div>

                    {/* Contact Info */}
                    <div className="flex items-center gap-4 mt-3 text-[#52525B] text-xs">
                      {lead.phone && (
                        <span className="flex items-center gap-1">
                          <Phone size={12} />
                          {lead.phone.slice(-4)}
                        </span>
                      )}
                      {lead.location && (
                        <span className="flex items-center gap-1">
                          <MapPin size={12} />
                          {lead.location}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </motion.div>
            ))
          )}
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

                <div className="grid grid-cols-6 gap-2 relative">
                  {LEAD_STATUSES.map((status) => {
                    const isSelected = newCustomer.lead_status === status;
                    return (
                      <button
                        key={status}
                        type="button"
                        onClick={() => {
                          setNewCustomer({ ...newCustomer, lead_status: status });
                          setLeadStatusTouched(true);
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
