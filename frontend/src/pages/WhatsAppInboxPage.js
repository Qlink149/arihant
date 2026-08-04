import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Building2,
  ExternalLink,
  Loader2,
  MessageCircle,
  Phone,
  RefreshCw,
  Search,
  Send,
  User,
  FileText,
  IndianRupee,
} from 'lucide-react';
import { toast } from 'sonner';
import { leadsAPI, whatsappAPI } from '../services/api';
import { Button } from '../components/ui/button';
import { ChatMessageBubble, useLeadWhatsAppThread } from '../components/whatsapp';
import { parseApiDate } from '../utils/datetime';

function initials(name) {
  const parts = String(name || '')
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!parts.length) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
}

function relativeTime(value) {
  const d = parseApiDate(value);
  if (!d) return '';
  const sec = Math.round((Date.now() - d.getTime()) / 1000);
  if (sec < 60) return 'just now';
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 7) return `${day}d ago`;
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
}

function Field({ label, value }) {
  if (value == null || value === '') return null;
  return (
    <div className="space-y-1">
      <p className="text-[11px] uppercase tracking-wide text-[#52525B]">{label}</p>
      <p className="text-sm text-[#E4E4E7] break-words">{value}</p>
    </div>
  );
}

const WhatsAppInboxPage = () => {
  const navigate = useNavigate();
  const [conversations, setConversations] = useState([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState(null);
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [leadDetail, setLeadDetail] = useState(null);
  const [leadLoading, setLeadLoading] = useState(false);
  const [draft, setDraft] = useState('');
  const [mobilePane, setMobilePane] = useState('list'); // list | chat | props
  const threadEndRef = useRef(null);
  const sendingAction = useRef(false);

  const selected = useMemo(
    () => conversations.find((c) => c.lead_id === selectedId) || null,
    [conversations, selectedId]
  );

  const {
    messages,
    loading: threadLoading,
    syncing,
    sending,
    sync,
    sendText,
  } = useLeadWhatsAppThread(selectedId, {
    phone: selected?.phone,
    autoLoad: Boolean(selectedId),
  });

  const fetchInbox = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setListLoading(true);
    setListError(null);
    try {
      const res = await whatsappAPI.getInbox({ limit: 50, skip: 0 });
      const rows = res.data?.conversations || [];
      setConversations(rows);
      setSelectedId((prev) => {
        if (prev && rows.some((r) => r.lead_id === prev)) return prev;
        return rows[0]?.lead_id || null;
      });
    } catch (err) {
      console.error('WhatsApp inbox failed', err);
      setListError('Could not load WhatsApp conversations');
      if (!silent) toast.error('Failed to load WhatsApp inbox');
    } finally {
      if (!silent) setListLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchInbox();
    const t = setInterval(() => fetchInbox({ silent: true }), 30000);
    return () => clearInterval(t);
  }, [fetchInbox]);

  useEffect(() => {
    if (!selectedId) {
      setLeadDetail(null);
      return undefined;
    }
    let cancelled = false;
    setLeadLoading(true);
    leadsAPI
      .getOne(selectedId)
      .then((res) => {
        if (!cancelled) setLeadDetail(res.data || null);
      })
      .catch(() => {
        if (!cancelled) setLeadDetail(null);
      })
      .finally(() => {
        if (!cancelled) setLeadLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, selectedId]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return conversations;
    return conversations.filter((c) => {
      const hay = `${c.display_name || ''} ${c.phone || ''} ${c.project || ''}`.toLowerCase();
      return hay.includes(q);
    });
  }, [conversations, query]);

  const selectConversation = (leadId) => {
    setSelectedId(leadId);
    setDraft('');
    setMobilePane('chat');
  };

  const handleSend = async () => {
    if (!draft.trim() || sending || sendingAction.current) return;
    sendingAction.current = true;
    const ok = await sendText(draft);
    sendingAction.current = false;
    if (ok) {
      setDraft('');
      fetchInbox({ silent: true });
    }
  };

  const runTemplateAction = async (label, fn) => {
    if (!selectedId || sendingAction.current) return;
    sendingAction.current = true;
    try {
      const res = await fn(selectedId);
      if (res.data?.success) {
        toast.success(`${label} sent`);
        await sync();
        fetchInbox({ silent: true });
      } else {
        toast.error(`Failed to send ${label.toLowerCase()}`, {
          description: res.data?.error,
        });
      }
    } catch {
      toast.error(`Failed to send ${label.toLowerCase()}`);
    } finally {
      sendingAction.current = false;
    }
  };

  const displayLead = leadDetail || selected;
  const displayName =
    displayLead?.display_name ||
    `${displayLead?.first_name || ''} ${displayLead?.last_name || ''}`.trim() ||
    displayLead?.phone ||
    'Conversation';

  return (
    <div className="h-[calc(100vh-5.5rem)] min-h-[480px] flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3 shrink-0">
        <div>
          <h1 className="font-serif text-2xl text-white flex items-center gap-2">
            <MessageCircle className="text-green-500" size={24} />
            WhatsApp
          </h1>
          <p className="text-[#52525B] text-sm mt-0.5">
            Conversations for leads you can work — reply in place
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => fetchInbox()}
          disabled={listLoading}
          className="border-white/10 text-[#A1A1AA] hover:text-white hover:bg-white/5"
        >
          {listLoading ? (
            <Loader2 size={14} className="animate-spin mr-1.5" />
          ) : (
            <RefreshCw size={14} className="mr-1.5" />
          )}
          Refresh
        </Button>
      </div>

      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[280px_minmax(0,1fr)_260px] gap-3">
        {/* Conversation list */}
        <aside
          className={`bg-[#141414] border border-white/10 rounded-xl flex flex-col min-h-0 ${
            mobilePane === 'list' ? 'flex' : 'hidden lg:flex'
          }`}
        >
          <div className="p-3 border-b border-white/10">
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#52525B]" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search name or phone"
                className="w-full h-10 pl-9 pr-3 rounded-lg bg-black/40 border border-white/10 text-sm text-white placeholder:text-[#52525B] focus:border-green-500/60 outline-none"
              />
            </div>
          </div>
          <div className="flex-1 overflow-y-auto">
            {listLoading && !conversations.length ? (
              <div className="flex items-center justify-center py-16 text-[#52525B]">
                <Loader2 className="animate-spin mr-2" size={18} />
                Loading…
              </div>
            ) : listError ? (
              <div className="p-6 text-center text-sm text-red-400">{listError}</div>
            ) : filtered.length === 0 ? (
              <div className="p-8 text-center text-[#52525B] text-sm">
                <MessageCircle className="mx-auto mb-2 opacity-50" size={32} />
                No WhatsApp conversations yet
              </div>
            ) : (
              filtered.map((c) => {
                const active = c.lead_id === selectedId;
                return (
                  <button
                    key={c.lead_id}
                    type="button"
                    onClick={() => selectConversation(c.lead_id)}
                    className={`w-full text-left px-3 py-3 border-b border-white/5 transition-colors ${
                      active ? 'bg-green-500/10' : 'hover:bg-white/5'
                    }`}
                  >
                    <div className="flex gap-3">
                      <div className="h-10 w-10 rounded-full bg-green-600/20 text-green-400 flex items-center justify-center text-xs font-semibold shrink-0">
                        {initials(c.display_name)}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-start justify-between gap-2">
                          <p className="text-sm text-white font-medium truncate">{c.display_name}</p>
                          <span className="text-[10px] text-[#52525B] shrink-0">
                            {relativeTime(c.last_message_at)}
                          </span>
                        </div>
                        <p className="text-xs text-[#A1A1AA] truncate mt-0.5">
                          {c.last_message_preview || '—'}
                        </p>
                        <div className="flex items-center gap-1.5 mt-1 text-[10px] text-green-500/90">
                          <MessageCircle size={10} />
                          <span className="truncate">{c.project || c.phone || 'WhatsApp'}</span>
                        </div>
                      </div>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </aside>

        {/* Chat thread */}
        <section
          className={`bg-[#141414] border border-white/10 rounded-xl flex flex-col min-h-0 ${
            mobilePane === 'chat' ? 'flex' : 'hidden lg:flex'
          }`}
        >
          {!selectedId ? (
            <div className="flex-1 flex items-center justify-center text-[#52525B] text-sm p-8">
              Select a conversation
            </div>
          ) : (
            <>
              <div className="px-4 py-3 border-b border-white/10 flex items-start justify-between gap-3 shrink-0">
                <div className="min-w-0">
                  <button
                    type="button"
                    className="lg:hidden text-xs text-[#A1A1AA] mb-1"
                    onClick={() => setMobilePane('list')}
                  >
                    ← Conversations
                  </button>
                  <h2 className="text-white font-medium truncate">{displayName}</h2>
                  <p className="text-xs text-[#52525B] truncate">{selected?.phone}</p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="lg:hidden text-[#A1A1AA]"
                    onClick={() => setMobilePane('props')}
                  >
                    Details
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={sync}
                    disabled={syncing}
                    className="border-white/10 text-[#A1A1AA] hover:text-white"
                  >
                    {syncing ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <RefreshCw size={14} />
                    )}
                  </Button>
                </div>
              </div>

              <div className="wa-chat-thread flex-1 overflow-y-auto px-4 py-4 space-y-3">
                {threadLoading && !messages.length ? (
                  <div className="flex justify-center py-16 text-[#52525B]">
                    <Loader2 className="animate-spin" size={20} />
                  </div>
                ) : messages.length === 0 ? (
                  <div className="text-center py-16 text-[#52525B]">
                    <MessageCircle className="mx-auto mb-3 opacity-50" size={36} />
                    <p>No messages yet</p>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={sync}
                      disabled={syncing}
                      className="mt-3 text-green-500"
                    >
                      Sync from WhatsApp
                    </Button>
                  </div>
                ) : (
                  messages.map((msg, idx) => (
                    <ChatMessageBubble
                      key={msg.id || msg.wati_message_id || idx}
                      msg={msg}
                    />
                  ))
                )}
                <div ref={threadEndRef} />
              </div>

              <div className="border-t border-white/10 p-3 space-y-2 shrink-0">
                <div className="flex flex-wrap gap-1.5">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 text-xs border-white/10 text-[#A1A1AA]"
                    onClick={() => runTemplateAction('Brochure', whatsappAPI.sendBrochure)}
                  >
                    Brochure
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 text-xs border-white/10 text-[#A1A1AA]"
                    onClick={() => runTemplateAction('Pricing', whatsappAPI.sendPricing)}
                  >
                    Pricing
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-7 text-xs border-white/10 text-[#A1A1AA]"
                    onClick={() =>
                      runTemplateAction('Site visit request', whatsappAPI.sendSiteVisitRequest)
                    }
                  >
                    Site visit
                  </Button>
                </div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
                    placeholder="Type a message..."
                    className="flex-1 h-11 px-4 bg-black/50 border border-white/10 rounded-full text-white text-sm placeholder:text-[#52525B] focus:border-green-500 outline-none"
                  />
                  <Button
                    type="button"
                    onClick={handleSend}
                    disabled={sending || !draft.trim()}
                    className="h-11 w-11 rounded-full bg-green-600 hover:bg-green-700 text-white p-0 disabled:opacity-50"
                  >
                    {sending ? (
                      <Loader2 size={18} className="animate-spin" />
                    ) : (
                      <Send size={18} />
                    )}
                  </Button>
                </div>
              </div>
            </>
          )}
        </section>

        {/* Lead properties */}
        <aside
          className={`bg-[#141414] border border-white/10 rounded-xl flex flex-col min-h-0 ${
            mobilePane === 'props' ? 'flex' : 'hidden lg:flex'
          }`}
        >
          <div className="px-4 py-3 border-b border-white/10 shrink-0">
            <button
              type="button"
              className="lg:hidden text-xs text-[#A1A1AA] mb-2"
              onClick={() => setMobilePane('chat')}
            >
              ← Chat
            </button>
            <h3 className="text-sm font-medium text-white">Lead details</h3>
            <p className="text-[11px] text-[#52525B] mt-0.5">CRM fields — not a ticket</p>
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {!selectedId ? (
              <p className="text-sm text-[#52525B]">No lead selected</p>
            ) : leadLoading && !displayLead ? (
              <div className="flex justify-center py-10 text-[#52525B]">
                <Loader2 className="animate-spin" size={18} />
              </div>
            ) : (
              <>
                <div className="flex items-center gap-3">
                  <div className="h-12 w-12 rounded-full bg-white/5 text-[#C5A059] flex items-center justify-center text-sm font-semibold">
                    {initials(displayName)}
                  </div>
                  <div className="min-w-0">
                    <p className="text-white font-medium truncate">{displayName}</p>
                    <p className="text-xs text-[#A1A1AA] flex items-center gap-1 truncate">
                      <Phone size={11} />
                      {displayLead?.phone || selected?.phone || '—'}
                    </p>
                  </div>
                </div>
                <Field
                  label="Project"
                  value={
                    displayLead?.project ? (
                      <span className="inline-flex items-center gap-1.5">
                        <Building2 size={13} className="text-[#C5A059]" />
                        {displayLead.project}
                      </span>
                    ) : null
                  }
                />
                <Field
                  label="Status"
                  value={displayLead?.status || displayLead?.pipeline_status}
                />
                <Field
                  label="Assignee"
                  value={
                    displayLead?.assigned_to_name || displayLead?.assigned_to ? (
                      <span className="inline-flex items-center gap-1.5">
                        <User size={13} />
                        {displayLead.assigned_to_name || displayLead.assigned_to}
                      </span>
                    ) : null
                  }
                />
                <Field
                  label="Budget"
                  value={
                    displayLead?.budget ? (
                      <span className="inline-flex items-center gap-1.5">
                        <IndianRupee size={13} />
                        {displayLead.budget}
                      </span>
                    ) : null
                  }
                />
                <Field
                  label="Configuration"
                  value={
                    displayLead?.configuration ? (
                      <span className="inline-flex items-center gap-1.5">
                        <FileText size={13} />
                        {displayLead.configuration}
                      </span>
                    ) : null
                  }
                />
                <div className="space-y-2 mt-2">
                  <Button
                    type="button"
                    className="w-full bg-[#C5A059]/15 text-[#C5A059] hover:bg-[#C5A059]/25 border border-[#C5A059]/30"
                    onClick={() => navigate(`/lead/${selectedId}#lead-overview`)}
                  >
                    <ExternalLink size={14} className="mr-2" />
                    Open Lead Overview
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full border-white/10 text-[#A1A1AA] hover:text-white hover:bg-white/5"
                    onClick={() => navigate(`/lead/${selectedId}`)}
                  >
                    <ExternalLink size={14} className="mr-2" />
                    Open Digital Twin
                  </Button>
                </div>
              </>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
};

export default WhatsAppInboxPage;
