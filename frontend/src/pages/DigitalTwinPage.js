import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { leadsAPI, whatsappAPI, usersAPI } from '../services/api';
import { LeadProfileHeader } from '../components/leads/LeadProfileHeader';
import { LeadAvatar } from '../components/leads/LeadAvatar';
import { StickySummaryBar } from '../components/leads/StickySummaryBar';
import { DataDnaGrid } from '../components/leads/DataDnaGrid';
import { RoleBasedTimeInput } from '../components/ui/RoleBasedTimeInput';
import { useAuth } from '../context/AuthContext';
import {
  getTimelineForDisplay,
  contextUpdateKey,
  formatTimelineAttribution,
  TIMELINE_INITIAL_VISIBLE,
  TIMELINE_LOAD_MORE_STEP,
} from '../utils/contextUpdates';
import { formatTimeIST, parseApiDate } from '../utils/datetime';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '../components/ui/accordion';
import { toast } from 'sonner';
import {
  ArrowLeft,
  Phone,
  MessageCircle,
  Bot,
  MapPin,
  Sparkles,
  Clock,
  Building,
  ChevronRight,
  PhoneCall,
  MessageSquare,
  User,
  UserPlus,
  TrendingUp,
  Send,
  History,
  X,
  Plus,
  ClipboardList,
  FileText,
  Mail,
  Video,
  StickyNote,
  AlertCircle,
  Target,
  Paperclip,
  Search,
  Loader2,
  RefreshCw,
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../components/ui/dialog';
import { ChatMessageBubble } from '../components/whatsapp';

// ─── Lead Quick Search (in-page search bar for lead detail) ───────────────────
const LeadQuickSearch = ({ currentLeadId }) => {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const wrapperRef = useRef(null);
  const inputRef = useRef(null);
  const debounceRef = useRef(null);

  // Close on outside click
  useEffect(() => {
    const handleMouseDown = (e) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleMouseDown);
    return () => document.removeEventListener('mousedown', handleMouseDown);
  }, []);

  const doSearch = useCallback(async (q) => {
    if (!q.trim()) { setResults([]); setOpen(false); return; }
    setLoading(true);
    try {
      // Regex search across all leads — same engine as the outer VC search bar.
      // Grant is minted on click (navigateToLead), not on search type.
      const res = await leadsAPI.getAll({ search: q.trim(), limit: 5, skip: 0 });
      const leads = Array.isArray(res.data) ? res.data : [];
      setResults(leads);
      setOpen(true);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);


  const handleChange = (e) => {
    const val = e.target.value;
    setQuery(val);
    clearTimeout(debounceRef.current);
    if (!val.trim()) { setResults([]); setOpen(false); return; }
    debounceRef.current = setTimeout(() => doSearch(val), 400);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') { setOpen(false); setQuery(''); setResults([]); }
    if (e.key === 'Enter' && results.length > 0) {
      navigateToLead(results[0]);
    }
  };

  const navigateToLead = (lead) => {
    setOpen(false);
    setQuery('');
    setResults([]);
    setExpanded(false);
    if (lead.id !== currentLeadId) {
      // Fire-and-forget: mint a 10-min edit grant so the rep can edit this lead.
      // No need to await — navigation can happen immediately.
      leadsAPI.grantSearchAccess(lead.id).catch(() => {});
      navigate(`/lead/${lead.id}`);
    }
  };

  const handleExpandToggle = () => {
    setExpanded((prev) => {
      if (!prev) setTimeout(() => inputRef.current?.focus(), 50);
      else { setOpen(false); setQuery(''); setResults([]); }
      return !prev;
    });
  };

  return (
    <div ref={wrapperRef} className="relative flex items-center">
      {/* Mobile: icon-only toggle */}
      <button
        type="button"
        onClick={handleExpandToggle}
        className={`flex items-center justify-center w-9 h-9 rounded-lg border transition-all duration-200 ${
          expanded
            ? 'bg-[#C5A059]/15 border-[#C5A059]/40 text-[#C5A059]'
            : 'bg-black/30 border-white/10 text-[#A1A1AA] hover:text-white hover:border-white/20'
        } lg:hidden`}
        aria-label="Search leads"
      >
        <Search size={16} />
      </button>

      {/* Desktop: always-visible compact search input */}
      <div className={`hidden lg:flex items-center relative`}>
        <Search size={15} className="absolute left-3 text-[#52525B] pointer-events-none z-10" />
        <Input
          ref={inputRef}
          value={query}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onFocus={() => { if (results.length > 0) setOpen(true); }}
          placeholder="Search any lead..."
          className="w-[230px] pl-9 pr-3 h-9 bg-black/40 border-white/10 text-white placeholder:text-[#52525B] text-sm focus:border-[#C5A059]/40 focus:ring-0 transition-all"
        />
        {loading && (
          <Loader2 size={14} className="absolute right-3 text-[#C5A059] animate-spin" />
        )}
      </div>

      {/* Mobile expanded input (overlay-style) */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 220, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="lg:hidden absolute right-10 flex items-center overflow-hidden"
          >
            <div className="relative w-full">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#52525B] pointer-events-none" />
              <Input
                ref={inputRef}
                value={query}
                onChange={handleChange}
                onKeyDown={handleKeyDown}
                onFocus={() => { if (results.length > 0) setOpen(true); }}
                placeholder="Search any lead..."
                className="w-full pl-8 pr-3 h-9 bg-[#111] border-white/15 text-white placeholder:text-[#52525B] text-sm"
              />
              {loading && (
                <Loader2 size={13} className="absolute right-3 top-1/2 -translate-y-1/2 text-[#C5A059] animate-spin" />
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Dropdown results */}
      <AnimatePresence>
        {open && (expanded || true) && (results.length > 0 || loading) && (
          <motion.div
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.15 }}
            className="absolute right-0 top-full mt-2 w-[320px] z-50 glass-card border border-white/10 rounded-xl shadow-2xl overflow-hidden"
          >
            {loading && results.length === 0 ? (
              <div className="flex items-center justify-center gap-2 py-5 text-[#A1A1AA] text-sm">
                <Loader2 size={15} className="animate-spin text-[#C5A059]" />
                Searching…
              </div>
            ) : results.length === 0 ? (
              <div className="py-5 text-center text-[#A1A1AA] text-sm">No leads found</div>
            ) : (
              <div className="max-h-72 overflow-y-auto">
                <div className="px-3 pt-2.5 pb-1 text-[10px] uppercase tracking-widest text-[#52525B] font-medium">
                  {results.length} result{results.length !== 1 ? 's' : ''}
                </div>
                {results.map((lead) => (
                  <button
                    key={lead.id}
                    type="button"
                    onClick={() => navigateToLead(lead)}
                    className={`w-full text-left px-3 py-2.5 flex items-start gap-3 hover:bg-white/5 transition-colors border-t border-white/5 first:border-0 ${
                      lead.id === currentLeadId ? 'bg-[#C5A059]/10' : ''
                    }`}
                  >
                    {/* Avatar */}
                    <div className="w-8 h-8 rounded-full bg-[#C5A059]/20 flex items-center justify-center text-[#C5A059] text-xs font-semibold shrink-0 mt-0.5">
                      {(lead.first_name?.[0] || '?').toUpperCase()}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-white text-sm font-medium truncate leading-tight">
                        {lead.first_name} {lead.last_name}
                        {lead.id === currentLeadId && (
                          <span className="ml-2 text-[10px] text-[#C5A059] font-normal">(current)</span>
                        )}
                      </p>
                      <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                        {lead.phone && (
                          <span className="text-[#A1A1AA] text-xs flex items-center gap-1">
                            <Phone size={10} />
                            {lead.phone}
                          </span>
                        )}
                        {(lead.presales_agent || lead.assigned_to_name) && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-white/5 text-[#52525B] border border-white/10">
                            {lead.presales_agent || lead.assigned_to_name}
                          </span>
                        )}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
            <div className="px-3 py-2 border-t border-white/5 text-[10px] text-[#52525B] flex items-center gap-1">
              <Search size={10} />
              Showing top 5 — type more to narrow
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

const DigitalTwinPage = () => {

  const { leadId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [lead, setLead] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showWhatsAppModal, setShowWhatsAppModal] = useState(false);
  const [showChatHistory, setShowChatHistory] = useState(false);
  const [chatHistory, setChatHistory] = useState([]);
  const [syncingChat, setSyncingChat] = useState(false);
  const [messageText, setMessageText] = useState('');
  const [sendingMessage, setSendingMessage] = useState(false);
  const [showContextModal, setShowContextModal] = useState(false);
  const [showTaskModal, setShowTaskModal] = useState(false);
  const [contextNote, setContextNote] = useState('');
  const [contextType, setContextType] = useState('general_note');
  const [savingContext, setSavingContext] = useState(false);
  const [waTemplates, setWaTemplates] = useState([]);
  const [waTemplatesLoaded, setWaTemplatesLoaded] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState(null);
  const [sendingBrochure, setSendingBrochure] = useState(false);
  const [sendingPricing, setSendingPricing] = useState(false);
  const [sendingSiteVisitReq, setSendingSiteVisitReq] = useState(false);
  const [sendingSiteVisitDone, setSendingSiteVisitDone] = useState(false);
  const [taskForm, setTaskForm] = useState({
    description: '', due_date: '', due_time: '', priority: 'medium',
    reminder_method: 'default', assigned_to: ''
  });
  const [savingTask, setSavingTask] = useState(false);
  const [assignees, setAssignees] = useState([]);
  const [loadingAssignees, setLoadingAssignees] = useState(false);
  const [timelineVisibleCount, setTimelineVisibleCount] = useState(TIMELINE_INITIAL_VISIBLE);
  const [stickySummaryVisible, setStickySummaryVisible] = useState(false);
  const [aiPersonaExpanded, setAiPersonaExpanded] = useState(false);
  const heroSentinelRef = useRef(null);
  const aiPollCount = useRef(0);

  const fetchLead = useCallback(async ({ silent = false } = {}) => {
    try {
      const response = await leadsAPI.getOne(leadId);
      setLead(response.data);
    } catch (error) {
      console.error('Failed to fetch lead:', error);
      if (!silent) toast.error('Failed to load lead details');
    } finally {
      if (!silent) setLoading(false);
    }
  }, [leadId]);

  const fetchSuggestions = useCallback(async () => {
    try {
      const response = await leadsAPI.getSuggestions(leadId);
      setSuggestions(response.data);
    } catch (error) {
      console.error('Failed to fetch suggestions:', error);
    }
  }, [leadId]);

  const handleLeadUpdated = useCallback(async () => {
    aiPollCount.current = 0;
    await fetchLead();
    fetchSuggestions();
  }, [fetchLead, fetchSuggestions]);

  useEffect(() => {
    fetchLead();
    fetchSuggestions();
  }, [fetchLead, fetchSuggestions]);

  useEffect(() => {
    setTimelineVisibleCount(TIMELINE_INITIAL_VISIBLE);
  }, [leadId]);

  // Deep-link from WhatsApp inbox "Open Lead Overview"
  useEffect(() => {
    if (!lead || location.hash !== '#lead-overview') return undefined;
    const t = window.setTimeout(() => {
      document.getElementById('lead-overview')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 80);
    return () => window.clearTimeout(t);
  }, [lead, location.hash, leadId]);

  useEffect(() => {
    const sentinel = heroSentinelRef.current;
    if (!sentinel) return undefined;
    const observer = new IntersectionObserver(
      ([entry]) => setStickySummaryVisible(!entry.isIntersecting),
      { root: null, rootMargin: '-56px 0px 0px 0px', threshold: 0 }
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [lead?.id]);

  useEffect(() => {
    let alive = true;
    setLoadingAssignees(true);
    usersAPI
      .listAssignees()
      .then(({ data }) => {
        if (!alive) return;
        setAssignees(Array.isArray(data) ? data : []);
      })
      .catch(() => {
        if (!alive) return;
        setAssignees([]);
      })
      .finally(() => {
        if (!alive) return;
        setLoadingAssignees(false);
      });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!showTaskModal || !lead) return;
    const defaultName = lead.assigned_to || lead.presales_agent || '';
    const matching = assignees.find((a) => a.full_name === defaultName);
    setTaskForm((prev) => ({
      ...prev,
      assigned_to: prev.assigned_to || matching?.full_name || defaultName,
    }));
  }, [showTaskModal, lead, assignees]);

  const fullTimeline = useMemo(
    () => getTimelineForDisplay(lead?.context_updates || []),
    [lead?.context_updates]
  );

  const visibleTimeline = useMemo(
    () => fullTimeline.slice(0, timelineVisibleCount),
    [fullTimeline, timelineVisibleCount]
  );

  const timelineHiddenCount = Math.max(0, fullTimeline.length - timelineVisibleCount);

  useEffect(() => {
    if (!lead?.ai_generation_pending || !lead?.ai_configured) {
      aiPollCount.current = 0;
      return undefined;
    }
    if (aiPollCount.current >= 8) return undefined;
    const delayMs = aiPollCount.current >= 2 ? 6000 : 4000;
    const t = setTimeout(() => {
      aiPollCount.current += 1;
      fetchLead({ silent: true });
    }, delayMs);
    return () => clearTimeout(t);
  }, [lead, fetchLead]);

  const sortChatAscending = (messages) => {
    const list = [...(messages || [])];
    list.sort(
      (a, b) =>
        (parseApiDate(a.created_at)?.getTime() ?? 0) -
        (parseApiDate(b.created_at)?.getTime() ?? 0)
    );
    return list;
  };

  const fetchChatHistory = async (showModal = true) => {
    try {
      // 1) Instant: show whatever we already have in Mongo
      const response = await whatsappAPI.getLeadChat(leadId);
      const localMessages = sortChatAscending(response.data.messages || []);
      setChatHistory(localMessages);
      if (showModal) setShowChatHistory(true);

      // 2) Always background-sync from WATI so OLD WhatsApp messages gap-fill into DB
      //    (even when Mongo already has a few CRM-sent templates). Idempotent upserts.
      setSyncingChat(true);
      try {
        const synced = await whatsappAPI.syncLeadChat(leadId);
        setChatHistory(sortChatAscending(synced.data.messages || []));
      } catch (syncErr) {
        console.warn('WhatsApp background sync skipped:', syncErr);
      } finally {
        setSyncingChat(false);
      }
    } catch (error) {
      console.error('Failed to fetch chat history:', error);
      if (showModal) toast.error('Failed to load chat history');
    }
  };

  const handleSyncChat = async () => {
    setSyncingChat(true);
    try {
      const res = await whatsappAPI.syncLeadChat(leadId);
      setChatHistory(sortChatAscending(res.data.messages || []));
      const n = res.data.synced ?? 0;
      toast.success(n ? `Synced ${n} message${n === 1 ? '' : 's'} from WhatsApp` : 'Chat up to date');
    } catch (error) {
      console.error('Failed to sync chat:', error);
      toast.error('Failed to sync from WhatsApp');
    } finally {
      setSyncingChat(false);
    }
  };

  // Fetch WATI templates when send modal opens
  const fetchWaTemplates = async () => {
    if (waTemplatesLoaded) return;
    try {
      const res = await whatsappAPI.getTemplates();
      const tpls = res.data?.templates || [];
      // Only show APPROVED templates
      setWaTemplates(tpls.filter((t) => t.status === 'APPROVED'));
    } catch {
      setWaTemplates([]);
    } finally {
      setWaTemplatesLoaded(true);
    }
  };

  const handleSendWhatsApp = async () => {
    if (!messageText.trim() && !selectedTemplate) {
      toast.error('Please enter a message or select a template');
      return;
    }

    setSendingMessage(true);
    try {
      const payload = {
        destination: lead.phone,
        message_type: selectedTemplate ? 'template' : 'text',
        text: messageText || undefined,
        template_name: selectedTemplate?.name || undefined,
        template_parameters: selectedTemplate
          ? [
              { name: 'name', value: lead.first_name || lead.phone },
              { name: 'project', value: lead.project || 'Arihant' },
            ]
          : undefined,
        broadcast_name: selectedTemplate ? 'arihant_crm' : undefined,
      };

      const response = await whatsappAPI.sendToLead(leadId, payload);

      if (response.data.success) {
        toast.success('WhatsApp message sent!', {
          description: `Delivered to ${lead.first_name}`,
        });
        setMessageText('');
        setSelectedTemplate(null);
        await fetchChatHistory(false);
        fetchLead();
      } else {
        const errMsg = response.data.error || 'Failed to send message';
        const low = errMsg.toLowerCase();
        if (low.includes('no open whatsapp') || low.includes('session') || low.includes('template')) {
          toast.error('Cannot send free-text right now', { description: errMsg });
        } else {
          toast.error('Message not sent', { description: errMsg });
        }
      }
    } catch (error) {
      console.error('Failed to send WhatsApp:', error);
      const detail =
        error?.response?.data?.error ||
        error?.response?.data?.detail ||
        'Network or server error. Please try again.';
      toast.error('Message not sent', { description: String(detail) });
    } finally {
      setSendingMessage(false);
    }
  };

  // Send message from chat history modal
  const handleSendFromChat = async () => {
    if (!messageText.trim()) return;

    setSendingMessage(true);
    try {
      const response = await whatsappAPI.sendToLead(leadId, {
        destination: lead.phone,
        message_type: 'text',
        text: messageText,
      });

      if (response.data.success) {
        setMessageText('');
        toast.success('Message sent');
        await fetchChatHistory(false);
        fetchLead();
      } else {
        const errMsg = response.data.error || 'Failed to send message';
        toast.error('Message not sent', { description: errMsg });
      }
    } catch (error) {
      const detail =
        error?.response?.data?.error ||
        error?.response?.data?.detail ||
        'Network or server error. Please try again.';
      toast.error('Message not sent', { description: String(detail) });
    } finally {
      setSendingMessage(false);
    }
  };

  // Send brochure PDF
  const handleSendBrochure = async () => {
    setSendingBrochure(true);
    try {
      const res = await whatsappAPI.sendBrochure(leadId);
      if (res.data.success) {
        toast.success('Brochure sent!', { description: 'PDF delivered to ' + lead.first_name });
        await fetchChatHistory(false);
        fetchLead();
      } else {
        toast.error('Failed to send brochure', { description: res.data.error });
      }
    } catch {
      toast.error('Failed to send brochure');
    } finally {
      setSendingBrochure(false);
    }
  };

  const handleSendPricing = async () => {
    setSendingPricing(true);
    try {
      const res = await whatsappAPI.sendPricing(leadId);
      if (res.data.success) {
        toast.success('Pricing info sent!');
        await fetchChatHistory(false);
        fetchLead();
      } else {
        toast.error('Failed to send pricing', { description: res.data.error });
      }
    } catch {
      toast.error('Failed to send pricing');
    } finally {
      setSendingPricing(false);
    }
  };

  const handleSendSiteVisitReq = async () => {
    setSendingSiteVisitReq(true);
    try {
      const res = await whatsappAPI.sendSiteVisitRequest(leadId);
      if (res.data.success) {
        toast.success('Site visit request sent!');
        await fetchChatHistory(false);
        fetchLead();
      } else {
        toast.error('Failed to send site visit request', { description: res.data.error });
      }
    } catch {
      toast.error('Failed to send site visit request');
    } finally {
      setSendingSiteVisitReq(false);
    }
  };

  const handleSendSiteVisitDone = async () => {
    setSendingSiteVisitDone(true);
    try {
      const res = await whatsappAPI.sendSiteVisitDone(leadId);
      if (res.data.success) {
        toast.success('Site visit completed sent!');
        await fetchChatHistory(false);
        fetchLead();
      } else {
        toast.error('Failed to send site visit completed', { description: res.data.error });
      }
    } catch {
      toast.error('Failed to send site visit completed');
    } finally {
      setSendingSiteVisitDone(false);
    }
  };

  const handleQuickMessage = (template) => {
    const messages = {
      greeting: `Hi ${lead.first_name}, thank you for your interest in Arihant ${lead.project}. I'm reaching out to assist you with your property requirements.`,
      followup: `Hi ${lead.first_name}, hope you're doing well! Just following up on our conversation about ${lead.project}. Would you like to schedule a site visit?`,
      brochure: `Hi ${lead.first_name}, here's the brochure for ${lead.project}. Feel free to reach out if you have any questions!`,
      sitevisit: `Hi ${lead.first_name}, we'd love to show you ${lead.project} in person. When would be a convenient time for a site visit?`
    };
    setMessageText(messages[template] || '');
  };

  const handleAICall = () => {
    toast.success('AI Call initiated! The AI agent will contact the lead shortly.', {
      description: `Calling ${lead.first_name} ${lead.last_name}...`
    });
  };

  const requiresPostNurtureTask =
    lead?.lead_status === 'Nurturing' &&
    Boolean(lead?.nurture_task_required_since_dt) &&
    !lead?.nurture_task_required_task_id;

  const handleSaveContext = async () => {
    if (!contextNote.trim()) { toast.error('Please enter a note'); return; }
    setSavingContext(true);
    try {
      await leadsAPI.addContext(leadId, { note: contextNote, update_type: contextType });
      toast.success('Context updated successfully');
      setContextNote('');
      setContextType('general_note');
      setShowContextModal(false);
      aiPollCount.current = 0;
      await handleLeadUpdated(); // Refresh timeline + trigger AI poll / portfolio
    } catch (error) {
      const msg = error?.response?.data?.detail;
      if (error?.response?.status === 409 && msg) {
        toast.error(msg);
        setShowContextModal(false);
        setShowTaskModal(true);
      } else {
        toast.error('Failed to save context update');
      }
    } finally { setSavingContext(false); }
  };

  const handleSaveTask = async () => {
    if (!taskForm.description.trim() || !taskForm.due_date) { toast.error('Please fill description and due date'); return; }
    setSavingTask(true);
    try {
      await leadsAPI.addTask(leadId, {
        ...taskForm,
        assigned_to: taskForm.assigned_to || lead?.assigned_to || lead?.presales_agent || ''
      });
      toast.success('Task created successfully');
      setTaskForm({ description: '', due_date: '', due_time: '', priority: 'medium', reminder_method: 'default', assigned_to: '' });
      setShowTaskModal(false);
      fetchLead();
    } catch (error) {
      toast.error('Failed to create task');
    } finally { setSavingTask(false); }
  };

  const getContextIcon = (type) => {
    switch (type) {
      case 'call': return PhoneCall;
      case 'whatsapp': return MessageSquare;
      case 'created': return User;
      case 'updated': return TrendingUp;
      case 'campaign': return Bot;
      case 'assigned': return UserPlus;
      case 'imported': return TrendingUp;
      case 'task': return ClipboardList;
      case 'site_visit': return MapPin;
      case 'email': return Mail;
      case 'meeting': return Video;
      case 'note': return StickyNote;
      default: return Clock;
    }
  };

  const changeLabel = (field) => {
    if (field === 'lead_status') return 'Lead Status';
    if (field === 'temperature') return 'Nurture Label';
    if (!field) return 'Updated';
    return String(field)
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase());
  };

  const changeValue = (v) => {
    if (v === null || v === undefined || v === '') return '—';
    if (typeof v === 'boolean') return v ? 'Yes' : 'No';
    return String(v);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-[#C5A059] animate-pulse">Loading profile...</div>
      </div>
    );
  }

  if (!lead) {
    return (
      <div className="text-center py-12">
        <p className="text-[#A1A1AA]">Lead not found</p>
        <Button onClick={() => navigate('/virtual-customer')} className="mt-4">
          Back to Leads
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <StickySummaryBar
        lead={lead}
        visible={stickySummaryVisible}
        onWhatsApp={() => setShowWhatsAppModal(true)}
        onAICall={handleAICall}
      />

      {/* Sticky Back + keep visible while scrolling lead overview */}
      <div className="sticky top-12 z-30 -mx-1 px-1 py-2 mb-1 bg-[#0A0A0A]/95 backdrop-blur-md border-b border-white/5">
        <motion.button
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          onClick={() => navigate(-1)}
          className="flex items-center gap-2 text-[#A1A1AA] hover:text-white transition-colors text-sm"
          data-testid="back-btn"
        >
          <ArrowLeft size={16} />
          Back to Explorer
        </motion.button>
      </div>

      {/* Compact lead header */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass-card rounded-lg p-3 lg:p-4 relative z-[25]"
        data-testid="lead-hero-section"
      >
        <div className="flex flex-col lg:flex-row lg:items-center gap-3">
          <LeadAvatar lead={lead} size="lg" className="hidden sm:flex" />

          <div className="flex-1 min-w-0">
            <LeadProfileHeader
              lead={lead}
              leadId={leadId}
              onLeadUpdated={handleLeadUpdated}
              compact
              contactSlot={(
                <>
                  {lead.phone && (
                    <span className="text-[#52525B] text-xs flex items-center gap-1">
                      <Phone size={12} />
                      {lead.phone}
                    </span>
                  )}
                  {lead.email && (
                    <span className="text-[#52525B] text-xs flex items-center gap-1">
                      <MessageCircle size={12} />
                      <span className="truncate max-w-[160px]">{lead.email}</span>
                    </span>
                  )}
                </>
              )}
            />
          </div>

          <div className="flex flex-wrap items-center gap-2 lg:shrink-0">
            {/* Quick Search — search any lead without leaving this page */}
            <LeadQuickSearch currentLeadId={leadId} />

            {/* Divider */}
            <div className="hidden lg:block w-px h-6 bg-white/10 mx-1" />

            <Button
              size="primary"
              onClick={() => setShowWhatsAppModal(true)}
              className="bg-green-600 hover:bg-green-700 text-white"
              data-testid="whatsapp-btn"
            >
              <MessageCircle size={16} className="mr-1.5" />
              WhatsApp
            </Button>
            <Button
              size="secondary"
              onClick={fetchChatHistory}
              variant="outline"
              className="border-green-600 text-green-500 hover:bg-green-600/10"
              data-testid="chat-history-btn"
            >
              <History size={16} className="mr-1.5" />
              History
            </Button>
            <Button
              size="primary"
              onClick={handleAICall}
              className="bg-[#C5A059] hover:bg-[#E5C079] text-black"
              data-testid="ai-call-btn"
            >
              <Bot size={16} className="mr-1.5" />
              AI Call
            </Button>
          </div>

        </div>
      </motion.div>
      <div ref={heroSentinelRef} className="h-px" aria-hidden="true" />

      {/* Lead Overview — sticky property grid */}
      <div id="lead-overview" className="scroll-mt-24">
      <DataDnaGrid
        lead={lead}
        leadId={leadId}
        onLeadUpdated={handleLeadUpdated}
        stickySummaryVisible={stickySummaryVisible}
      />
      </div>

      {lead.ai_generation_pending && lead.ai_configured && (
        <div className="rounded-lg border border-[#C5A059]/40 bg-[#C5A059]/10 px-4 py-3 text-sm text-[#E5C079] flex items-center gap-2">
          <Sparkles size={16} className="shrink-0" />
          AI insights are refreshing from the latest WhatsApp, notes, and lead overview. This page will update automatically.
        </div>
      )}

      {!lead.ai_configured && (
        <div className="rounded-lg border border-white/10 bg-black/30 px-4 py-3 text-sm text-[#A1A1AA]">
          Live AI is not configured (set <span className="font-mono text-[#C5A059]">GROQ_API_KEY</span> on the server). Persona and strategic moves will appear once keys are added.
        </div>
      )}

      {/* AI Persona Summary */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="glass-card rounded-lg p-3 lg:p-4 ai-glow"
        data-testid="ai-persona-section"
      >
        <div className="flex items-center justify-between gap-2 mb-2">
          <div className="flex items-center gap-2">
            <Sparkles className="text-[#C5A059]" size={16} />
            <h2 className="text-base font-semibold text-white">AI Persona Summary</h2>
          </div>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => setAiPersonaExpanded((v) => !v)}
            className="h-7 px-2 text-[#52525B] hover:text-white text-xs"
            data-testid="ai-persona-toggle"
          >
            {aiPersonaExpanded ? 'Collapse' : 'Expand'}
          </Button>
        </div>
        <p className={`text-[#A1A1AA] text-sm leading-relaxed ${aiPersonaExpanded ? '' : 'line-clamp-3'}`}>
          {lead.ai_persona_summary ||
            (lead.ai_configured
              ? 'Insights will appear shortly after notes or calls are loaded (refresh if you just added context).'
              : 'AI persona summary not available for this lead.')}
        </p>
      </motion.div>

      {(Array.isArray(lead.strategic_next_moves) && lead.strategic_next_moves.length > 0) ||
      suggestions.length > 0 ? (
        <Accordion type="multiple" className="space-y-2">
          {Array.isArray(lead.strategic_next_moves) && lead.strategic_next_moves.length > 0 && (
            <AccordionItem
              value="strategic-moves"
              className="glass-card rounded-lg border-l-4 border-emerald-600/60 border-b-0 px-4"
              data-testid="ai-strategic-moves-section"
            >
              <AccordionTrigger className="hover:no-underline py-3">
                <div className="flex items-center gap-2 text-left">
                  <TrendingUp className="text-emerald-400 shrink-0" size={16} />
                  <span className="text-base font-semibold text-white">AI strategic next moves</span>
                  <span className="text-[#52525B] text-xs font-normal">from conversations</span>
                </div>
              </AccordionTrigger>
              <AccordionContent>
                <div className="space-y-3 pb-2">
                  {lead.strategic_next_moves.map((move, idx) => (
                    <div
                      key={idx}
                      className="p-3 bg-black/30 rounded-lg border border-white/5"
                    >
                      <p className="text-white font-medium">{move.title || `Step ${idx + 1}`}</p>
                      <p className="text-[#A1A1AA] text-sm mt-1">{move.rationale}</p>
                      {move.priority && (
                        <span className="inline-block mt-2 text-xs text-[#C5A059] capitalize">{move.priority}</span>
                      )}
                    </div>
                  ))}
                </div>
              </AccordionContent>
            </AccordionItem>
          )}

          {suggestions.length > 0 && (
            <AccordionItem
              value="portfolio-suggestions"
              className="glass-card rounded-lg border-l-4 border-[#C5A059] border-b-0 px-4"
              data-testid="strategic-move-section"
            >
              <AccordionTrigger className="hover:no-underline py-3">
                <div className="flex items-center gap-2 text-left">
                  <Target className="text-[#C5A059] shrink-0" size={16} />
                  <span className="text-base font-semibold text-white">Portfolio suggestions</span>
                  <span className="text-[#52525B] text-xs font-normal">cross-project</span>
                </div>
              </AccordionTrigger>
              <AccordionContent>
                <div className="space-y-3 pb-2">
                  {suggestions.map((suggestion, idx) => (
                    <div
                      key={idx}
                      className="flex items-center justify-between p-3 bg-black/30 rounded-lg hover:bg-black/40 transition-colors"
                    >
                      <div className="flex items-center gap-3">
                        <Building className="text-[#C5A059]" size={18} />
                        <div>
                          <p className="text-white font-medium">{suggestion.project}</p>
                          <p className="text-[#52525B] text-sm">{suggestion.reason}</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-[#C5A059] text-sm">
                          {Math.round(suggestion.match_score * 100)}% match
                        </span>
                        <ChevronRight className="text-[#52525B]" size={16} />
                      </div>
                    </div>
                  ))}
                </div>
              </AccordionContent>
            </AccordionItem>
          )}
        </Accordion>
      ) : null}

      {/* Context Updates Timeline */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        className="glass-card rounded-lg p-3 lg:p-4"
        data-testid="context-timeline"
      >
        <div className="flex items-center justify-between mb-3 gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <Clock className="text-[#C5A059]" size={16} />
            <h2 className="text-base font-semibold text-white">Context Updates Timeline</h2>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex flex-col items-end gap-1">
              <Button
                size="sm"
                onClick={() => {
                  if (requiresPostNurtureTask) {
                    toast.error('Create a follow-up task first after moving lead to Nurturing.');
                    setShowTaskModal(true);
                    return;
                  }
                  setShowContextModal(true);
                }}
                className="bg-[#C5A059] text-black hover:bg-[#E5C079] h-8 px-3 text-xs disabled:opacity-60"
                data-testid="update-context-btn"
                disabled={savingTask || savingContext}
              >
                <Plus size={14} className="mr-1" /> Add Note
              </Button>
              {requiresPostNurtureTask && (
                <div className="text-[10px] text-amber-400/90 max-w-[320px] text-right">
                  Create a follow-up task first after moving lead to Nurturing.
                </div>
              )}
            </div>
            <Button size="sm" onClick={() => setShowTaskModal(true)}
              className="bg-transparent border border-[#C5A059] text-[#C5A059] hover:bg-[#C5A059]/10 h-8 px-3 text-xs"
              data-testid="add-task-btn">
              <ClipboardList size={14} className="mr-1" /> Add Task
            </Button>
            {requiresPostNurtureTask && (
              <Button
                size="sm"
                onClick={() => setShowTaskModal(true)}
                className="bg-amber-500/15 border border-amber-500/30 text-amber-300 hover:bg-amber-500/20 h-8 px-3 text-xs"
                data-testid="create-follow-up-task-btn"
              >
                Create Follow-Up Task
              </Button>
            )}
          </div>
        </div>

        <div className="timeline-line space-y-3">
          {visibleTimeline.map((update, idx) => {
            const IconComponent = getContextIcon(update.type);
            const isNew = idx === 0;
            const attribution = formatTimelineAttribution(update);

            return (
              <motion.div
                key={contextUpdateKey(update)}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: idx * 0.1 }}
                className="relative pl-8"
              >
                {/* Icon */}
                <div className={`absolute left-0 w-5 h-5 rounded-full flex items-center justify-center ${
                  isNew ? 'bg-[#C5A059] gold-glow' : 'bg-[#1A1A1A] border border-white/10'
                }`}>
                  <IconComponent size={10} className={isNew ? 'text-black' : 'text-[#A1A1AA]'} />
                </div>

                {/* Content */}
                <div className={`p-3 rounded-lg ${isNew ? 'bg-[#C5A059]/10 border border-[#C5A059]/30' : 'bg-black/30'}`}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded uppercase tracking-wider ${
                      isNew ? 'bg-[#C5A059] text-black' : 'bg-white/10 text-[#A1A1AA]'
                    }`}>
                      {update.type}
                    </span>
                  </div>
                  <p className="text-[#C5A059] text-xs font-medium mt-1" data-testid="timeline-attribution">
                    {attribution.label}
                  </p>
                  {update.type === 'updated' && Array.isArray(update.changes) && update.changes.length > 0 ? (
                    <div className="mt-2 space-y-1.5" data-testid="timeline-changes">
                      {update.changes.map((c, i) => (
                        <div key={`${c.field || 'field'}-${i}`} className="text-sm text-white/90 flex flex-wrap gap-2">
                          <span className="text-[#A1A1AA]">{changeLabel(c.field)}:</span>
                          <span className="text-white">{changeValue(c.from)}</span>
                          <span className="text-[#52525B]">→</span>
                          <span className="text-white">{changeValue(c.to)}</span>
                        </div>
                      ))}
                      {update.description && (
                        <p className="text-[#52525B] text-xs mt-2">{update.description}</p>
                      )}
                    </div>
                  ) : (
                    <p className="text-white mt-2">{update.description}</p>
                  )}
                  
                  {/* Call specific details */}
                  {update.type === 'call' && update.key_points && (
                    <div className="mt-3 p-3 bg-black/30 rounded">
                      <p className="text-[#C5A059] text-xs uppercase tracking-wider mb-2">Key Points</p>
                      <ul className="text-[#A1A1AA] text-sm space-y-1">
                        {update.key_points.map((point, i) => (
                          <li key={i}>• {point}</li>
                        ))}
                      </ul>
                      {update.next_steps && (
                        <div className="mt-2 pt-2 border-t border-white/10">
                          <p className="text-[#C5A059] text-xs">Next Steps: {update.next_steps}</p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </motion.div>
            );
          })}
        </div>
        {timelineHiddenCount > 0 && (
          <div className="mt-6 flex justify-center">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() =>
                setTimelineVisibleCount((n) =>
                  Math.min(n + TIMELINE_LOAD_MORE_STEP, fullTimeline.length)
                )
              }
              className="border-white/10 text-[#A1A1AA] hover:bg-white/5 hover:text-white"
              data-testid="timeline-load-more"
            >
              Load older activity (
              {Math.min(timelineHiddenCount, TIMELINE_LOAD_MORE_STEP)}
              {timelineHiddenCount > TIMELINE_LOAD_MORE_STEP ? '+' : ''} more)
            </Button>
          </div>
        )}
      </motion.div>

      {/* Update Context Modal */}
      <Dialog open={showContextModal} onOpenChange={setShowContextModal}>
        <DialogContent className="bg-[#1A1A1A] border-white/10 text-white max-w-lg" data-testid="context-modal">
          <DialogHeader>
            <DialogTitle className="font-serif text-xl flex items-center gap-2">
              <FileText className="text-[#C5A059]" size={22} /> Update Context
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <label className="text-[#52525B] text-xs uppercase tracking-wider block mb-2">Update Type</label>
              <select value={contextType} onChange={e => setContextType(e.target.value)}
                className="w-full h-10 px-3 bg-black/50 border border-white/10 rounded-lg text-white text-sm"
                data-testid="context-type-select">
                <option value="call_note">Call Note</option>
                <option value="site_visit_note">Site Visit Note</option>
                <option value="whatsapp_update">WhatsApp Update</option>
                <option value="email_update">Email Update</option>
                <option value="meeting_note">Meeting Note</option>
                <option value="general_note">General Note</option>
              </select>
            </div>
            <div>
              <label className="text-[#52525B] text-xs uppercase tracking-wider block mb-2">Note</label>
              <textarea value={contextNote} onChange={e => setContextNote(e.target.value)}
                placeholder="e.g., Customer visited site today, liked the 3BHK layout, wants possession by Dec 2026..."
                className="w-full h-32 px-4 py-3 bg-black/50 border border-white/10 rounded-lg text-white placeholder:text-[#52525B] resize-none"
                data-testid="context-note-input" />
            </div>
            <p className="text-[#52525B] text-xs">This note will be added to the timeline and the AI Summary will be regenerated.</p>
            <div className="flex gap-3">
              <Button variant="outline" onClick={() => setShowContextModal(false)} className="flex-1 border-white/10 text-white hover:bg-white/5">Cancel</Button>
              <Button onClick={handleSaveContext} disabled={savingContext || !contextNote.trim()}
                className="flex-1 bg-[#C5A059] text-black hover:bg-[#E5C079] disabled:opacity-50" data-testid="save-context-btn">
                {savingContext ? 'Saving...' : 'Save Update'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Add Task Modal */}
      <Dialog open={showTaskModal} onOpenChange={setShowTaskModal}>
        <DialogContent className="bg-[#1A1A1A] border-white/10 text-white max-w-lg" data-testid="task-modal">
          <DialogHeader>
            <DialogTitle className="font-serif text-xl flex items-center gap-2">
              <ClipboardList className="text-[#C5A059]" size={22} /> Add Task
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <label className="text-[#52525B] text-xs uppercase tracking-wider block mb-2">Task Description</label>
              <textarea value={taskForm.description} onChange={e => setTaskForm({...taskForm, description: e.target.value})}
                placeholder="e.g., Schedule site visit for Reserve 16..."
                className="w-full h-20 px-4 py-3 bg-black/50 border border-white/10 rounded-lg text-white placeholder:text-[#52525B] resize-none"
                data-testid="task-description-input" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[#52525B] text-xs uppercase tracking-wider block mb-2">Due Date</label>
                <input type="date" value={taskForm.due_date} onChange={e => setTaskForm({...taskForm, due_date: e.target.value})}
                  className="w-full h-10 px-3 bg-black/50 border border-white/10 rounded-lg text-white text-sm" data-testid="task-due-date" />
              </div>
              <div>
                <label className="text-[#52525B] text-xs uppercase tracking-wider block mb-2">Due Time</label>
                <RoleBasedTimeInput
                  value={taskForm.due_time}
                  onChange={(due_time) => setTaskForm({ ...taskForm, due_time })}
                  isAdmin={isAdmin}
                  testId="task-due-time"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[#52525B] text-xs uppercase tracking-wider block mb-2">Priority</label>
                <select value={taskForm.priority} onChange={e => setTaskForm({...taskForm, priority: e.target.value})}
                  className="w-full h-10 px-3 bg-black/50 border border-white/10 rounded-lg text-white text-sm" data-testid="task-priority">
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                </select>
              </div>
              <div>
                <label className="text-[#52525B] text-xs uppercase tracking-wider block mb-2">Reminder</label>
                <select
                  value={taskForm.reminder_method}
                  disabled
                  className="w-full h-10 px-3 bg-black/50 border border-white/10 rounded-lg text-white text-sm opacity-70 cursor-not-allowed"
                  data-testid="task-reminder"
                >
                  <option value="default">Default</option>
                </select>
              </div>
            </div>
            <div>
              <label className="text-[#52525B] text-xs uppercase tracking-wider block mb-2">Assign To</label>
              <select
                value={taskForm.assigned_to}
                onChange={(e) => setTaskForm({ ...taskForm, assigned_to: e.target.value })}
                className="w-full h-10 px-3 bg-black/50 border border-white/10 rounded-lg text-white text-sm"
                data-testid="task-assigned-to"
                disabled={loadingAssignees}
              >
                <option value="">
                  {loadingAssignees ? 'Loading agents…' : 'Select agent'}
                </option>
                {taskForm.assigned_to &&
                  !assignees.some((u) => u.full_name === taskForm.assigned_to) && (
                    <option value={taskForm.assigned_to}>{taskForm.assigned_to}</option>
                  )}
                {assignees.map((u) => (
                  <option key={u.id} value={u.full_name}>
                    {u.full_name}{u.role ? ` (${u.role})` : ''}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex gap-3">
              <Button variant="outline" onClick={() => setShowTaskModal(false)} className="flex-1 border-white/10 text-white hover:bg-white/5">Cancel</Button>
              <Button onClick={handleSaveTask} disabled={savingTask || !taskForm.description.trim() || !taskForm.due_date}
                className="flex-1 bg-[#C5A059] text-black hover:bg-[#E5C079] disabled:opacity-50" data-testid="save-task-btn">
                {savingTask ? 'Creating...' : 'Create Task'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* WhatsApp Send Modal */}
      <Dialog open={showWhatsAppModal} onOpenChange={(open) => {
        setShowWhatsAppModal(open);
        if (open) { setSelectedTemplate(null); fetchWaTemplates(); }
      }}>
        <DialogContent className="bg-[#1A1A1A] border-white/10 text-white max-w-lg">
          <DialogHeader>
            <DialogTitle className="font-serif text-xl flex items-center gap-2">
              <MessageCircle className="text-green-500" size={24} />
              Send WhatsApp to {lead?.first_name}
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <p className="text-[#A1A1AA] text-sm">
              Sending to: {lead?.phone}
            </p>
            
            {/* WATI Template picker (shown when APPROVED templates available) */}
            {waTemplatesLoaded && waTemplates.length > 0 && (
              <div className="space-y-2">
                <p className="text-[#52525B] text-xs uppercase tracking-wider">Approved Templates</p>
                <select
                  value={selectedTemplate?.name || ''}
                  onChange={(e) => {
                    const tpl = waTemplates.find((t) => t.name === e.target.value) || null;
                    setSelectedTemplate(tpl);
                    if (tpl) setMessageText('');
                  }}
                  className="w-full h-10 px-3 bg-black/50 border border-white/10 rounded-lg text-white text-sm focus:border-green-500"
                  data-testid="template-select"
                >
                  <option value="">— Free text (session) —</option>
                  {waTemplates.map((t) => (
                    <option key={t.id || t.name} value={t.name}>{t.name}</option>
                  ))}
                </select>
                {selectedTemplate && (
                  <p className="text-[#52525B] text-xs">
                    Template body: {selectedTemplate.body || selectedTemplate.hsm || '—'}
                  </p>
                )}
              </div>
            )}

            {waTemplatesLoaded && waTemplates.length === 0 && (
              <div className="text-xs text-amber-400 bg-amber-900/20 border border-amber-500/20 rounded px-3 py-2">
                ⚠ No approved templates yet — free text only if a session is open (customer messaged within 24h).
              </div>
            )}

            {/* Quick fill buttons (pre-fill text area only) */}
            {!selectedTemplate && (
              <div className="space-y-2">
                <p className="text-[#52525B] text-xs uppercase tracking-wider">Quick Fill</p>
                <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => handleQuickMessage('greeting')}
                  className="px-3 py-1 text-xs bg-black/50 border border-white/10 rounded hover:border-green-500/50 transition-colors"
                >
                  Greeting
                </button>
                <button
                  onClick={() => handleQuickMessage('followup')}
                  className="px-3 py-1 text-xs bg-black/50 border border-white/10 rounded hover:border-green-500/50 transition-colors"
                >
                  Follow Up
                </button>
                <button
                  onClick={() => handleQuickMessage('brochure')}
                  className="px-3 py-1 text-xs bg-black/50 border border-white/10 rounded hover:border-green-500/50 transition-colors"
                >
                  Brochure
                </button>
                <button
                  onClick={() => handleQuickMessage('sitevisit')}
                  className="px-3 py-1 text-xs bg-black/50 border border-white/10 rounded hover:border-green-500/50 transition-colors"
                >
                  Site Visit
                </button>
              </div>
            </div>
            )}

            {/* Message Input — hidden when a template is selected */}
            {!selectedTemplate && (
            <div>
              <textarea
                value={messageText}
                onChange={(e) => setMessageText(e.target.value)}
                placeholder="Type your message..."
                className="w-full h-32 px-4 py-3 bg-black/50 border border-white/10 rounded-lg text-white placeholder:text-[#52525B] resize-none focus:border-green-500 transition-colors"
                data-testid="whatsapp-message-input"
              />
            </div>
            )}

            <div className="flex gap-3">
              <Button
                variant="outline"
                onClick={() => setShowWhatsAppModal(false)}
                className="flex-1 border-white/10 text-white hover:bg-white/5"
              >
                Cancel
              </Button>
              <Button
                onClick={handleSendWhatsApp}
                disabled={sendingMessage || (!messageText.trim() && !selectedTemplate)}
                className="flex-1 bg-green-600 hover:bg-green-700 text-white disabled:opacity-50"
                data-testid="send-whatsapp-btn"
              >
                {sendingMessage ? (
                  <span className="flex items-center gap-2">
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                    Sending...
                  </span>
                ) : (
                  <span className="flex items-center gap-2">
                    <Send size={16} />
                    Send Message
                  </span>
                )}
              </Button>
            </div>

            {/* Send Brochure — enabled when PDF URL is configured on server */}
            <div className="border-t border-white/10 pt-3">
              <Button
                onClick={handleSendBrochure}
                disabled={sendingBrochure}
                variant="outline"
                className="w-full border-white/10 text-[#A1A1AA] hover:bg-white/5 hover:text-white disabled:opacity-50"
                data-testid="send-brochure-btn"
              >
                {sendingBrochure ? (
                  <span className="flex items-center gap-2">
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Sending Brochure...
                  </span>
                ) : (
                  <span className="flex items-center gap-2">
                    <Paperclip size={15} />
                    Send Brochure PDF
                  </span>
                )}
              </Button>
              <p className="text-[#52525B] text-xs text-center mt-1">
                Requires active session · PDF URL configured on server
              </p>
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2 border-t border-white/10 pt-3">
              {/* Send Pricing */}
              <Button
                onClick={handleSendPricing}
                disabled={sendingPricing}
                variant="outline"
                className="w-full border-white/10 text-[#A1A1AA] hover:bg-white/5 hover:text-white disabled:opacity-50"
              >
                {sendingPricing ? (
                  <span className="flex items-center gap-2">
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Sending Pricing...
                  </span>
                ) : (
                  <span className="flex items-center gap-2">
                    <Send size={15} />
                    Send Pricing Info
                  </span>
                )}
              </Button>

              {/* Send Site Visit Request */}
              <Button
                onClick={handleSendSiteVisitReq}
                disabled={sendingSiteVisitReq}
                variant="outline"
                className="w-full border-white/10 text-[#A1A1AA] hover:bg-white/5 hover:text-white disabled:opacity-50"
              >
                {sendingSiteVisitReq ? (
                  <span className="flex items-center gap-2">
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Sending Request...
                  </span>
                ) : (
                  <span className="flex items-center gap-2">
                    <Send size={15} />
                    Site Visit Request
                  </span>
                )}
              </Button>

              {/* Send Site Visit Done */}
              <Button
                onClick={handleSendSiteVisitDone}
                disabled={sendingSiteVisitDone}
                variant="outline"
                className="w-full border-white/10 text-[#A1A1AA] hover:bg-white/5 hover:text-white disabled:opacity-50 md:col-span-2"
              >
                {sendingSiteVisitDone ? (
                  <span className="flex items-center gap-2">
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Sending Thank You...
                  </span>
                ) : (
                  <span className="flex items-center gap-2">
                    <Send size={15} />
                    Site Visit Completed
                  </span>
                )}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Chat History Modal */}
      <Dialog open={showChatHistory} onOpenChange={setShowChatHistory}>
        <DialogContent className="bg-[#1A1A1A] border-white/10 text-white max-w-2xl max-h-[90vh] flex flex-col">
          <DialogHeader className="flex-shrink-0">
            <div className="flex items-start justify-between gap-3 pr-6">
              <div>
                <DialogTitle className="font-serif text-xl flex items-center gap-2">
                  <MessageCircle className="text-green-500" size={24} />
                  Chat with {lead?.first_name} {lead?.last_name}
                </DialogTitle>
                <p className="text-[#52525B] text-sm">{lead?.phone}</p>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleSyncChat}
                disabled={syncingChat}
                className="border-white/10 text-[#A1A1AA] hover:text-white hover:bg-white/5 shrink-0"
                data-testid="chat-sync-btn"
              >
                {syncingChat ? (
                  <Loader2 size={14} className="animate-spin mr-1.5" />
                ) : (
                  <RefreshCw size={14} className="mr-1.5" />
                )}
                Sync
              </Button>
            </div>
          </DialogHeader>
          
          {/* Chat Messages */}
          <div className="wa-chat-thread flex-1 overflow-y-auto py-4 space-y-3 min-h-[300px] max-h-[400px]" data-testid="chat-messages">
            {chatHistory.length === 0 ? (
              <div className="text-center py-12 text-[#52525B]">
                <MessageCircle className="mx-auto mb-3" size={40} />
                <p className="text-lg">No messages yet</p>
                <p className="text-sm mt-1">Start a conversation with {lead?.first_name}</p>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={handleSyncChat}
                  disabled={syncingChat}
                  className="mt-3 text-green-500 hover:text-green-400"
                >
                  {syncingChat ? 'Syncing…' : 'Sync from WhatsApp'}
                </Button>
              </div>
            ) : (
              chatHistory.map((msg, idx) => (
                <ChatMessageBubble key={msg.id || msg.wati_message_id || idx} msg={msg} />
              ))
            )}
          </div>

          {/* Message Input */}
          <div className="flex-shrink-0 pt-4 border-t border-white/10">
            <div className="flex gap-2">
              <input
                type="text"
                value={messageText}
                onChange={(e) => setMessageText(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSendFromChat()}
                placeholder="Type a message..."
                className="flex-1 h-12 px-4 bg-black/50 border border-white/10 rounded-full text-white placeholder:text-[#52525B] focus:border-green-500 transition-colors"
                data-testid="chat-message-input"
              />
              <Button
                onClick={handleSendFromChat}
                disabled={sendingMessage || !messageText.trim()}
                className="h-12 w-12 rounded-full bg-green-600 hover:bg-green-700 text-white disabled:opacity-50 p-0"
                data-testid="chat-send-btn"
              >
                {sendingMessage ? (
                  <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                ) : (
                  <Send size={20} />
                )}
              </Button>
            </div>
            <p className="text-[#52525B] text-xs mt-2 text-center">
              Press Enter to send • Messages sent via WhatsApp
            </p>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default DigitalTwinPage;
