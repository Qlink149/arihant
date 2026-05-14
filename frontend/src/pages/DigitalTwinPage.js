import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { leadsAPI, whatsappAPI } from '../services/api';
import { toast } from 'sonner';
import {
  ArrowLeft,
  Phone,
  MessageCircle,
  Bot,
  MapPin,
  Briefcase,
  Home,
  DollarSign,
  Calendar,
  Target,
  Sparkles,
  Clock,
  Building,
  ChevronRight,
  PhoneCall,
  MessageSquare,
  User,
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
  UserPlus
} from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../components/ui/dialog';

const DigitalTwinPage = () => {
  const { leadId } = useParams();
  const navigate = useNavigate();
  const [lead, setLead] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showWhatsAppModal, setShowWhatsAppModal] = useState(false);
  const [showChatHistory, setShowChatHistory] = useState(false);
  const [chatHistory, setChatHistory] = useState([]);
  const [messageText, setMessageText] = useState('');
  const [sendingMessage, setSendingMessage] = useState(false);
  const [showContextModal, setShowContextModal] = useState(false);
  const [showTaskModal, setShowTaskModal] = useState(false);
  const [contextNote, setContextNote] = useState('');
  const [contextType, setContextType] = useState('general_note');
  const [savingContext, setSavingContext] = useState(false);
  const [taskForm, setTaskForm] = useState({
    description: '', due_date: '', due_time: '', priority: 'medium',
    reminder_method: 'email', assigned_to: ''
  });
  const [savingTask, setSavingTask] = useState(false);
  const [savingPipeline, setSavingPipeline] = useState(false);
  const aiPollCount = useRef(0);

  const PIPELINE_OPTIONS = [
    { value: '', label: 'Not set' },
    { value: 'Qualified', label: 'Qualified' },
    { value: 'VIP', label: 'VIP' },
    { value: 'Nurture', label: 'Nurture' },
    { value: 'Standard', label: 'Standard' },
  ];

  useEffect(() => {
    fetchLead();
    fetchSuggestions();
  }, [leadId]);

  const fetchLead = useCallback(async () => {
    try {
      const response = await leadsAPI.getOne(leadId);
      setLead(response.data);
    } catch (error) {
      console.error('Failed to fetch lead:', error);
      toast.error('Failed to load lead details');
    } finally {
      setLoading(false);
    }
  }, [leadId]);

  useEffect(() => {
    if (!lead?.ai_generation_pending || !lead?.ai_configured) {
      aiPollCount.current = 0;
      return undefined;
    }
    if (aiPollCount.current >= 8) return undefined;
    const t = setTimeout(() => {
      aiPollCount.current += 1;
      fetchLead();
    }, 4000);
    return () => clearTimeout(t);
  }, [lead, fetchLead]);

  const fetchSuggestions = async () => {
    try {
      const response = await leadsAPI.getSuggestions(leadId);
      setSuggestions(response.data);
    } catch (error) {
      console.error('Failed to fetch suggestions:', error);
    }
  };

  const fetchChatHistory = async (showModal = true) => {
    try {
      const response = await whatsappAPI.getLeadChat(leadId);
      const messages = response.data.messages || [];
      // Sort messages by date (oldest first for chat view)
      messages.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
      setChatHistory(messages);
      if (showModal) setShowChatHistory(true);
    } catch (error) {
      console.error('Failed to fetch chat history:', error);
      if (showModal) toast.error('Failed to load chat history');
    }
  };

  const handleSendWhatsApp = async () => {
    if (!messageText.trim()) {
      toast.error('Please enter a message');
      return;
    }

    setSendingMessage(true);
    try {
      const response = await whatsappAPI.sendToLead(leadId, {
        destination: lead.phone,
        message_type: 'text',
        text: messageText
      });

      if (response.data.success) {
        toast.success('WhatsApp message sent successfully!', {
          description: `Message delivered to ${lead.first_name}`
        });
        setMessageText('');
        // Refresh chat history to show the new message
        await fetchChatHistory(false);
        // Refresh lead to show updated context
        fetchLead();
      } else {
        toast.error('Failed to send message', {
          description: response.data.error || 'Please try again'
        });
      }
    } catch (error) {
      console.error('Failed to send WhatsApp:', error);
      toast.error('Failed to send WhatsApp message');
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
        text: messageText
      });

      if (response.data.success) {
        setMessageText('');
        // Refresh chat history
        await fetchChatHistory(false);
        fetchLead();
      } else {
        toast.error('Failed to send message');
      }
    } catch (error) {
      toast.error('Failed to send message');
    } finally {
      setSendingMessage(false);
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

  const handleSaveContext = async () => {
    if (!contextNote.trim()) { toast.error('Please enter a note'); return; }
    setSavingContext(true);
    try {
      await leadsAPI.addContext(leadId, { note: contextNote, update_type: contextType });
      toast.success('Context updated successfully');
      setContextNote('');
      setContextType('general_note');
      setShowContextModal(false);
      fetchLead(); // Refresh to show new entry + updated AI summary
    } catch (error) {
      toast.error('Failed to save context update');
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
      setTaskForm({ description: '', due_date: '', due_time: '', priority: 'medium', reminder_method: 'email', assigned_to: '' });
      setShowTaskModal(false);
      fetchLead();
    } catch (error) {
      toast.error('Failed to create task');
    } finally { setSavingTask(false); }
  };

  const handlePipelineCategoryChange = async (value) => {
    setSavingPipeline(true);
    try {
      await leadsAPI.update(leadId, { pipeline_category: value || null });
      toast.success('Pipeline category updated');
      await fetchLead();
    } catch (error) {
      toast.error('Failed to update pipeline category');
    } finally {
      setSavingPipeline(false);
    }
  };

  const handleAutoAssign = async () => {
    try {
      const response = await leadsAPI.autoAssign(leadId);
      if (response.data.assigned_to) {
        toast.success(`Assigned to ${response.data.assigned_to} (${response.data.active_leads} active leads)`);
        fetchLead();
      } else {
        toast.error('No sales managers available for assignment');
      }
    } catch (error) {
      toast.error('Auto-assignment failed');
    }
  };

  const getTemperatureColor = (temp) => {
    switch (temp) {
      case 'Hot': return 'text-red-500 bg-red-500/20';
      case 'Warm': return 'text-orange-500 bg-orange-500/20';
      case 'Cold': return 'text-blue-500 bg-blue-500/20';
      default: return 'text-gray-500 bg-gray-500/20';
    }
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
    <div className="space-y-6">
      {/* Back Button */}
      <motion.button
        initial={{ opacity: 0, x: -20 }}
        animate={{ opacity: 1, x: 0 }}
        onClick={() => navigate(-1)}
        className="flex items-center gap-2 text-[#A1A1AA] hover:text-white transition-colors"
        data-testid="back-btn"
      >
        <ArrowLeft size={18} />
        Back to Explorer
      </motion.button>

      {/* Branded Header Strip */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="relative rounded-xl overflow-hidden h-20"
      >
        <div className="absolute inset-0 bg-gradient-to-r from-[#0A0A0A] via-[#1A1A1A] to-[#C5A059]/20" />
        <div className="relative z-10 h-full flex items-center px-6 justify-between">
          <div className="flex items-center gap-4">
            <Building className="text-[#C5A059]" size={24} />
            <div>
              <p className="text-[#C5A059] font-serif text-lg">{lead.project || 'No Project Assigned'}</p>
              <p className="text-[#52525B] text-xs">Managed by {lead.assigned_to || lead.presales_agent || 'Unassigned'}</p>
            </div>
          </div>
          <Button size="sm" onClick={handleAutoAssign}
            className="bg-transparent border border-[#C5A059]/40 text-[#C5A059] hover:bg-[#C5A059]/10 h-8 px-3 text-xs"
            data-testid="auto-assign-btn">
            <UserPlus size={14} className="mr-1" /> Auto Assign
          </Button>
        </div>
      </motion.div>

      {/* Hero Section */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="glass-card rounded-lg p-6 lg:p-8"
        data-testid="lead-hero-section"
      >
        <div className="flex flex-col lg:flex-row lg:items-start gap-6">
          {/* Avatar */}
          <div className="flex-shrink-0">
            <div className="w-24 h-24 lg:w-32 lg:h-32 rounded-full bg-[#C5A059]/20 flex items-center justify-center text-[#C5A059] font-serif text-4xl lg:text-5xl">
              {lead.first_name?.charAt(0)}{lead.last_name?.charAt(0)}
            </div>
          </div>

          {/* Profile Details */}
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="font-serif text-3xl text-white">
                {lead.first_name} {lead.last_name}
              </h1>
              <span className={`px-3 py-1 rounded-full text-sm font-medium ${getTemperatureColor(lead.temperature)}`}>
                {lead.temperature}
              </span>
              {lead.vip && (
                <span className="px-3 py-1 rounded-full text-sm font-medium bg-purple-500/20 text-purple-400">
                  VIP
                </span>
              )}
              {lead.pipeline_category && (
                <span className="px-3 py-1 rounded-full text-sm font-medium bg-amber-500/20 text-amber-400">
                  {lead.pipeline_category}
                </span>
              )}
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-3">
              <label className="text-[#52525B] text-xs uppercase tracking-wider">Pipeline category</label>
              <select
                value={lead.pipeline_category || ''}
                onChange={(e) => handlePipelineCategoryChange(e.target.value)}
                disabled={savingPipeline}
                className="h-9 min-w-[180px] px-3 bg-black/50 border border-white/10 rounded-lg text-white text-sm disabled:opacity-50"
                data-testid="pipeline-category-select"
              >
                {PIPELINE_OPTIONS.map((o) => (
                  <option key={o.value || 'unset'} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              {savingPipeline && <span className="text-[#52525B] text-xs">Saving...</span>}
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-4">
              <div className="flex items-center gap-2 text-[#A1A1AA]">
                <Briefcase size={16} className="text-[#C5A059]" />
                <span>{lead.designation || 'Not specified'}</span>
              </div>
              <div className="flex items-center gap-2 text-[#A1A1AA]">
                <MapPin size={16} className="text-[#C5A059]" />
                <span>{lead.location || 'Not specified'}</span>
              </div>
              <div className="flex items-center gap-2 text-[#A1A1AA]">
                <Home size={16} className="text-[#C5A059]" />
                <span>{lead.current_residence_type || 'Not specified'}</span>
              </div>
            </div>

            {/* Contact Info */}
            <div className="flex flex-wrap items-center gap-4 mt-4 text-[#52525B] text-sm">
              {lead.phone && (
                <span className="flex items-center gap-1">
                  <Phone size={14} />
                  {lead.phone}
                </span>
              )}
              {lead.email && (
                <span className="flex items-center gap-1">
                  <MessageCircle size={14} />
                  {lead.email}
                </span>
              )}
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex flex-col gap-3 lg:ml-auto">
            <Button
              onClick={() => setShowWhatsAppModal(true)}
              className="bg-green-600 hover:bg-green-700 text-white"
              data-testid="whatsapp-btn"
            >
              <MessageCircle size={18} className="mr-2" />
              Send WhatsApp
            </Button>
            <Button
              onClick={fetchChatHistory}
              variant="outline"
              className="border-green-600 text-green-500 hover:bg-green-600/10"
              data-testid="chat-history-btn"
            >
              <History size={18} className="mr-2" />
              Chat History
            </Button>
            <Button
              onClick={handleAICall}
              className="bg-[#C5A059] hover:bg-[#E5C079] text-black"
              data-testid="ai-call-btn"
            >
              <Bot size={18} className="mr-2" />
              Trigger AI Call
            </Button>
          </div>
        </div>
      </motion.div>

      {lead.ai_generation_pending && lead.ai_configured && (
        <div className="rounded-lg border border-[#C5A059]/40 bg-[#C5A059]/10 px-4 py-3 text-sm text-[#E5C079] flex items-center gap-2">
          <Sparkles size={16} className="shrink-0" />
          AI insights are refreshing in the background from the latest notes and calls. This page will update automatically.
        </div>
      )}

      {!lead.ai_configured && (
        <div className="rounded-lg border border-white/10 bg-black/30 px-4 py-3 text-sm text-[#A1A1AA]">
          Live AI is not configured (set <span className="font-mono text-[#C5A059]">GROK_API_KEY_1</span> etc. on the server). Persona and strategic moves will appear once keys are added.
        </div>
      )}

      {/* AI Persona Summary */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="glass-card rounded-lg p-6 ai-glow"
        data-testid="ai-persona-section"
      >
        <div className="flex items-center gap-2 mb-4">
          <Sparkles className="text-[#C5A059]" size={20} />
          <h2 className="font-serif text-xl text-white">AI Persona Summary</h2>
        </div>
        <p className="text-[#A1A1AA] leading-relaxed">
          {lead.ai_persona_summary ||
            (lead.ai_configured
              ? 'Insights will appear shortly after notes or calls are loaded (refresh if you just added context).'
              : 'AI persona summary not available for this lead.')}
        </p>
      </motion.div>

      {/* AI strategic next moves (Grok) */}
      {Array.isArray(lead.strategic_next_moves) && lead.strategic_next_moves.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.12 }}
          className="glass-card rounded-lg p-6 border-l-4 border-emerald-600/60"
          data-testid="ai-strategic-moves-section"
        >
          <div className="flex items-center gap-2 mb-4">
            <TrendingUp className="text-emerald-400" size={20} />
            <h2 className="font-serif text-xl text-white">AI strategic next moves</h2>
            <span className="text-[#52525B] text-xs ml-2">from conversations</span>
          </div>
          <div className="space-y-3">
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
        </motion.div>
      )}

      {/* Portfolio cross-pitch suggestions */}
      {suggestions.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.15 }}
          className="glass-card rounded-lg p-6 border-l-4 border-[#C5A059]"
          data-testid="strategic-move-section"
        >
          <div className="flex items-center gap-2 mb-4">
            <Target className="text-[#C5A059]" size={20} />
            <h2 className="font-serif text-xl text-white">Portfolio suggestions</h2>
            <span className="text-[#52525B] text-xs ml-2">cross-project</span>
          </div>
          <div className="space-y-3">
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
        </motion.div>
      )}

      {/* Data DNA Grid */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="grid grid-cols-2 lg:grid-cols-5 gap-4"
        data-testid="data-dna-grid"
      >
        <div className="glass-card rounded-lg p-4 text-center">
          <DollarSign className="mx-auto text-[#C5A059]" size={24} />
          <p className="text-[#52525B] text-xs uppercase tracking-wider mt-2">Budget</p>
          <p className="text-white font-medium mt-1">{lead.budget || 'Not specified'}</p>
          {lead.ai_grounded_profile?.budget && lead.ai_grounded_profile.budget !== 'Not specified' && (
            <p className="text-[#737373] text-xs mt-1">From conversations (AI): {lead.ai_grounded_profile.budget}</p>
          )}
        </div>
        <div className="glass-card rounded-lg p-4 text-center">
          <Home className="mx-auto text-[#C5A059]" size={24} />
          <p className="text-[#52525B] text-xs uppercase tracking-wider mt-2">Configuration</p>
          <p className="text-white font-medium mt-1">{lead.configuration || 'Not specified'}</p>
          {lead.ai_grounded_profile?.configuration && lead.ai_grounded_profile.configuration !== 'Not specified' && (
            <p className="text-[#737373] text-xs mt-1">From conversations (AI): {lead.ai_grounded_profile.configuration}</p>
          )}
        </div>
        <div className="glass-card rounded-lg p-4 text-center">
          <Calendar className="mx-auto text-[#C5A059]" size={24} />
          <p className="text-[#52525B] text-xs uppercase tracking-wider mt-2">Possession</p>
          <p className="text-white font-medium mt-1">{lead.possession_requirement || 'Not specified'}</p>
          {lead.ai_grounded_profile?.possession_requirement && lead.ai_grounded_profile.possession_requirement !== 'Not specified' && (
            <p className="text-[#737373] text-xs mt-1">From conversations (AI): {lead.ai_grounded_profile.possession_requirement}</p>
          )}
        </div>
        <div className="glass-card rounded-lg p-4 text-center">
          <MapPin className="mx-auto text-[#C5A059]" size={24} />
          <p className="text-[#52525B] text-xs uppercase tracking-wider mt-2">Location</p>
          <p className="text-white font-medium mt-1">{lead.location || 'Not specified'}</p>
        </div>
        <div className="glass-card rounded-lg p-4 text-center">
          <Target className="mx-auto text-[#C5A059]" size={24} />
          <p className="text-[#52525B] text-xs uppercase tracking-wider mt-2">Purpose</p>
          <p className="text-white font-medium mt-1">{lead.reason_for_purchase || lead.intent || 'Unknown'}</p>
          {lead.ai_grounded_profile?.intent && lead.ai_grounded_profile.intent !== 'Not specified' && (
            <p className="text-[#737373] text-xs mt-1">From conversations (AI): {lead.ai_grounded_profile.intent}</p>
          )}
        </div>
      </motion.div>

      {/* Context Updates Timeline */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        className="glass-card rounded-lg p-6"
        data-testid="context-timeline"
      >
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2">
            <Clock className="text-[#C5A059]" size={20} />
            <h2 className="font-serif text-xl text-white">Context Updates Timeline</h2>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={() => setShowContextModal(true)}
              className="bg-[#C5A059] text-black hover:bg-[#E5C079] h-8 px-3 text-xs"
              data-testid="update-context-btn">
              <Plus size={14} className="mr-1" /> Update Context
            </Button>
            <Button size="sm" onClick={() => setShowTaskModal(true)}
              className="bg-transparent border border-[#C5A059] text-[#C5A059] hover:bg-[#C5A059]/10 h-8 px-3 text-xs"
              data-testid="add-task-btn">
              <ClipboardList size={14} className="mr-1" /> Add Task
            </Button>
          </div>
        </div>

        <div className="timeline-line space-y-6">
          {(lead.context_updates || []).slice().reverse().map((update, idx) => {
            const IconComponent = getContextIcon(update.type);
            const isNew = idx === 0;
            
            return (
              <motion.div
                key={idx}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: idx * 0.1 }}
                className="relative pl-10"
              >
                {/* Icon */}
                <div className={`absolute left-0 w-6 h-6 rounded-full flex items-center justify-center ${
                  isNew ? 'bg-[#C5A059] gold-glow' : 'bg-[#1A1A1A] border border-white/10'
                }`}>
                  <IconComponent size={12} className={isNew ? 'text-black' : 'text-[#A1A1AA]'} />
                </div>

                {/* Content */}
                <div className={`p-4 rounded-lg ${isNew ? 'bg-[#C5A059]/10 border border-[#C5A059]/30' : 'bg-black/30'}`}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className={`text-xs px-2 py-0.5 rounded uppercase tracking-wider ${
                        isNew ? 'bg-[#C5A059] text-black' : 'bg-white/10 text-[#A1A1AA]'
                      }`}>
                        {update.type}
                      </span>
                      {update.agent && (
                        <span className="text-[#52525B] text-xs">{update.agent}</span>
                      )}
                    </div>
                    <span className="text-[#52525B] text-xs">
                      {new Date(update.timestamp).toLocaleDateString('en-IN', {
                        day: 'numeric',
                        month: 'short',
                        year: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit'
                      })}
                    </span>
                  </div>
                  <p className="text-white mt-2">{update.description}</p>
                  
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
                <input type="time" value={taskForm.due_time} onChange={e => setTaskForm({...taskForm, due_time: e.target.value})}
                  className="w-full h-10 px-3 bg-black/50 border border-white/10 rounded-lg text-white text-sm" data-testid="task-due-time" />
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
                <select value={taskForm.reminder_method} onChange={e => setTaskForm({...taskForm, reminder_method: e.target.value})}
                  className="w-full h-10 px-3 bg-black/50 border border-white/10 rounded-lg text-white text-sm" data-testid="task-reminder">
                  <option value="email">Email</option>
                  <option value="whatsapp">WhatsApp</option>
                  <option value="both">Both</option>
                </select>
              </div>
            </div>
            <div>
              <label className="text-[#52525B] text-xs uppercase tracking-wider block mb-2">Assign To</label>
              <input type="text" value={taskForm.assigned_to} onChange={e => setTaskForm({...taskForm, assigned_to: e.target.value})}
                placeholder={lead?.assigned_to || lead?.presales_agent || 'Sales manager name'}
                className="w-full h-10 px-3 bg-black/50 border border-white/10 rounded-lg text-white text-sm placeholder:text-[#52525B]"
                data-testid="task-assigned-to" />
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
      <Dialog open={showWhatsAppModal} onOpenChange={setShowWhatsAppModal}>
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
            
            {/* Quick Templates */}
            <div className="space-y-2">
              <p className="text-[#52525B] text-xs uppercase tracking-wider">Quick Templates</p>
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

            {/* Message Input */}
            <div>
              <textarea
                value={messageText}
                onChange={(e) => setMessageText(e.target.value)}
                placeholder="Type your message..."
                className="w-full h-32 px-4 py-3 bg-black/50 border border-white/10 rounded-lg text-white placeholder:text-[#52525B] resize-none focus:border-green-500 transition-colors"
                data-testid="whatsapp-message-input"
              />
            </div>

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
                disabled={sendingMessage || !messageText.trim()}
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
          </div>
        </DialogContent>
      </Dialog>

      {/* Chat History Modal */}
      <Dialog open={showChatHistory} onOpenChange={setShowChatHistory}>
        <DialogContent className="bg-[#1A1A1A] border-white/10 text-white max-w-2xl max-h-[90vh] flex flex-col">
          <DialogHeader className="flex-shrink-0">
            <DialogTitle className="font-serif text-xl flex items-center gap-2">
              <MessageCircle className="text-green-500" size={24} />
              Chat with {lead?.first_name} {lead?.last_name}
            </DialogTitle>
            <p className="text-[#52525B] text-sm">{lead?.phone}</p>
          </DialogHeader>
          
          {/* Chat Messages */}
          <div className="flex-1 overflow-y-auto py-4 space-y-3 min-h-[300px] max-h-[400px]" data-testid="chat-messages">
            {chatHistory.length === 0 ? (
              <div className="text-center py-12 text-[#52525B]">
                <MessageCircle className="mx-auto mb-3" size={40} />
                <p className="text-lg">No messages yet</p>
                <p className="text-sm mt-1">Start a conversation with {lead?.first_name}</p>
              </div>
            ) : (
              chatHistory.map((msg, idx) => (
                <div
                  key={msg.id || idx}
                  className={`flex ${msg.direction === 'outbound' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[75%] px-4 py-3 rounded-2xl ${
                      msg.direction === 'outbound'
                        ? 'bg-green-600 text-white rounded-br-md'
                        : 'bg-[#262626] text-white rounded-bl-md'
                    }`}
                  >
                    <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                    <div className={`flex items-center gap-2 mt-1 text-xs ${
                      msg.direction === 'outbound' ? 'text-green-200' : 'text-[#52525B]'
                    }`}>
                      <span>
                        {new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                      {msg.direction === 'outbound' && msg.status && (
                        <span className="capitalize">• {msg.status}</span>
                      )}
                    </div>
                  </div>
                </div>
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
              Press Enter to send • Messages sent via Gupshup WhatsApp
            </p>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default DigitalTwinPage;
