import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Building2,
  ExternalLink,
  Loader2,
  MessageCircle,
  Phone,
  Plus,
  RefreshCw,
  Search,
  Send,
  User,
  UserPlus,
  FileText,
  IndianRupee,
} from 'lucide-react';
import { toast } from 'sonner';
import { leadsAPI, whatsappAPI } from '../services/api';
import { Button } from '../components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../components/ui/dialog';
import { ChatMessageBubble, useLeadWhatsAppThread } from '../components/whatsapp';
import { CANONICAL_PROJECTS } from '../constants/leadPicklists';
import { parseApiDate } from '../utils/datetime';

const PAGE_SIZE = 40;
const FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'unread', label: 'Unread' },
  { id: 'mine', label: 'Mine' },
];

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

function conversationKeyOf(c) {
  if (!c) return null;
  if (c.conversation_key) return c.conversation_key;
  if (c.lead_id) return `lead:${c.lead_id}`;
  if (c.peer_phone || c.phone) return `peer:${c.peer_phone || c.phone}`;
  return null;
}

function leadDisplayName(lead) {
  const fromParts = `${lead?.first_name || ''} ${lead?.last_name || ''}`.trim();
  return fromParts || lead?.name || lead?.phone || 'Lead';
}

function looksLikeFullPhone(raw) {
  const digits = String(raw || '').replace(/\D/g, '');
  return digits.length >= 10 && digits.length <= 15;
}

function Field({ label, value }) {
  if (value == null || value === '') return null;
  return (
    <div className="space-y-1">
      <p className="text-[11px] uppercase tracking-wide text-crm-fg-muted">{label}</p>
      <p className="text-sm text-[#E4E4E7] break-words">{value}</p>
    </div>
  );
}

const WhatsAppInboxPage = () => {
  const navigate = useNavigate();
  const [conversations, setConversations] = useState([]);
  const [listLoading, setListLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [listError, setListError] = useState(null);
  const [listFilter, setListFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [selectedKey, setSelectedKey] = useState(null);
  const [leadDetail, setLeadDetail] = useState(null);
  const [leadLoading, setLeadLoading] = useState(false);
  const [draft, setDraft] = useState('');
  const [mobilePane, setMobilePane] = useState('list');
  const [leadHits, setLeadHits] = useState([]);
  const [leadSearchLoading, setLeadSearchLoading] = useState(false);
  const [showLeadDropdown, setShowLeadDropdown] = useState(false);
  const [waTemplates, setWaTemplates] = useState([]);
  const [waTemplatesLoaded, setWaTemplatesLoaded] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createSubmitting, setCreateSubmitting] = useState(false);
  const [createForm, setCreateForm] = useState({
    first_name: '',
    last_name: '',
    phone: '',
    project: '',
    lead_source: 'WhatsApp',
  });

  const threadEndRef = useRef(null);
  const sendingAction = useRef(false);
  const listRef = useRef(null);
  const searchWrapRef = useRef(null);

  const selected = useMemo(
    () => conversations.find((c) => conversationKeyOf(c) === selectedKey) || null,
    [conversations, selectedKey]
  );

  const {
    messages,
    loading: threadLoading,
    syncing,
    sending,
    sessionOpen,
    sync,
    sendText,
    sendTemplate,
  } = useLeadWhatsAppThread(selected?.lead_id || null, {
    phone: selected?.peer_phone || selected?.phone || null,
    autoLoad: Boolean(selectedKey),
  });

  const fetchInbox = useCallback(
    async ({ silent = false, append = false, skip = 0 } = {}) => {
      if (!silent && !append) setListLoading(true);
      if (append) setLoadingMore(true);
      if (!append) setListError(null);
      try {
        const res = await whatsappAPI.getInbox({
          limit: PAGE_SIZE,
          skip,
          filter: listFilter,
          q: debouncedQuery || undefined,
        });
        const rows = res.data?.conversations || [];
        setHasMore(Boolean(res.data?.has_more));
        setConversations((prev) => {
          if (!append) {
            const serverKeys = new Set(rows.map(conversationKeyOf).filter(Boolean));
            const ephemeral = prev.filter((c) => {
              const key = conversationKeyOf(c);
              return (
                key &&
                !serverKeys.has(key) &&
                !c.last_message_at &&
                Boolean(c.lead_id)
              );
            });
            return [...ephemeral, ...rows];
          }
          const seen = new Set(prev.map(conversationKeyOf));
          const merged = [...prev];
          for (const row of rows) {
            const key = conversationKeyOf(row);
            if (key && !seen.has(key)) {
              seen.add(key);
              merged.push(row);
            }
          }
          return merged;
        });
        setSelectedKey((prev) => {
          if (prev) return prev;
          return conversationKeyOf(rows[0]) || null;
        });
      } catch (err) {
        console.error('WhatsApp inbox failed', err);
        setListError('Could not load WhatsApp conversations');
        if (!silent) toast.error('Failed to load WhatsApp inbox');
      } finally {
        if (!silent && !append) setListLoading(false);
        if (append) setLoadingMore(false);
      }
    },
    [listFilter, debouncedQuery]
  );

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query.trim()), 400);
    return () => clearTimeout(t);
  }, [query]);

  useEffect(() => {
    setSelectedKey(null);
  }, [listFilter]);

  useEffect(() => {
    fetchInbox({ skip: 0 });
  }, [listFilter, debouncedQuery, fetchInbox]);

  useEffect(() => {
    const tick = () => {
      const ms = document.visibilityState === 'visible' ? 8000 : 30000;
      return setInterval(() => fetchInbox({ silent: true, skip: 0 }), ms);
    };
    let id = tick();
    const onVis = () => {
      clearInterval(id);
      id = tick();
      if (document.visibilityState === 'visible') fetchInbox({ silent: true, skip: 0 });
    };
    document.addEventListener('visibilitychange', onVis);
    return () => {
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [fetchInbox]);

  // CRM lead search for "Start chat with…"
  useEffect(() => {
    const q = debouncedQuery;
    if (!q || q.length < 2) {
      setLeadHits([]);
      setShowLeadDropdown(false);
      return undefined;
    }
    let cancelled = false;
    setLeadSearchLoading(true);
    (async () => {
      try {
        let hits = [];
        if (looksLikeFullPhone(q)) {
          try {
            const exact = await leadsAPI.exactLookup({ phone: q.replace(/\D/g, '') });
            if (exact.data?.id) hits = [exact.data];
          } catch {
            /* 404 → fall through to list search */
          }
        }
        if (!hits.length) {
          const res = await leadsAPI.getAll({ search: q, limit: 8, skip: 0 });
          hits = Array.isArray(res.data) ? res.data : res.data?.leads || [];
        }
        if (!cancelled) {
          setLeadHits(hits.slice(0, 8));
          setShowLeadDropdown(true);
        }
      } catch (err) {
        console.warn('Lead search failed', err);
        if (!cancelled) setLeadHits([]);
      } finally {
        if (!cancelled) setLeadSearchLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [debouncedQuery]);

  useEffect(() => {
    const onDoc = (e) => {
      if (searchWrapRef.current && !searchWrapRef.current.contains(e.target)) {
        setShowLeadDropdown(false);
      }
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  useEffect(() => {
    if (!selected?.lead_id) {
      setLeadDetail(null);
      return undefined;
    }
    let cancelled = false;
    setLeadLoading(true);
    leadsAPI
      .getOne(selected.lead_id)
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
  }, [selected?.lead_id]);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, selectedKey]);

  // Mark read when opening a thread
  useEffect(() => {
    if (!selectedKey) return undefined;
    const conv = conversations.find((c) => conversationKeyOf(c) === selectedKey);
    if (!conv) return undefined;
    const peer = conv.peer_phone || conv.phone;
    if (!peer && !conv.lead_id) return undefined;
    whatsappAPI
      .markInboxRead({
        peer_phone: peer || undefined,
        lead_id: conv.lead_id || undefined,
      })
      .then(() => {
        setConversations((prev) =>
          prev.map((c) =>
            conversationKeyOf(c) === selectedKey ? { ...c, unread_count: 0 } : c
          )
        );
      })
      .catch(() => {});
    return undefined;
    // Intentionally only when selection changes — not on every conversations refresh
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKey]);

  useEffect(() => {
    if (waTemplatesLoaded) return;
    whatsappAPI
      .getTemplates()
      .then((res) => {
        const tpls = res.data?.templates || [];
        setWaTemplates(tpls.filter((t) => t.status === 'APPROVED'));
      })
      .catch(() => setWaTemplates([]))
      .finally(() => setWaTemplatesLoaded(true));
  }, [waTemplatesLoaded]);

  const selectConversation = (key) => {
    setSelectedKey(key);
    setDraft('');
    setSelectedTemplate(null);
    setMobilePane('chat');
    setShowLeadDropdown(false);
  };

  const openLeadChat = async (lead) => {
    if (!lead?.id) return;
    try {
      leadsAPI.grantSearchAccess(lead.id).catch(() => {});
    } catch {
      /* optional grant */
    }
    const phone = lead.phone || lead.normalized_phone || '';
    const key = `lead:${lead.id}`;
    setConversations((prev) => {
      if (prev.some((c) => conversationKeyOf(c) === key)) return prev;
      return [
        {
          conversation_key: key,
          lead_id: lead.id,
          is_unmatched: false,
          peer_phone: phone,
          display_name: leadDisplayName(lead),
          phone,
          project: lead.project,
          assigned_to_name: lead.assigned_to_name,
          status: lead.lead_status || lead.status,
          budget: lead.budget,
          configuration: lead.configuration,
          last_message_preview: 'Start a conversation',
          last_message_at: null,
          unread_count: 0,
          session_open: false,
        },
        ...prev,
      ];
    });
    setQuery('');
    setDebouncedQuery('');
    setShowLeadDropdown(false);
    selectConversation(key);
  };

  const handleSend = async () => {
    if (sending || sendingAction.current) return;
    if (selectedTemplate) {
      sendingAction.current = true;
      const name = selected?.display_name || leadDetail?.first_name || 'Customer';
      const project = selected?.project || leadDetail?.project || 'Arihant';
      const ok = await sendTemplate({
        templateName: selectedTemplate.name,
        templateParameters: [
          { name: 'name', value: String(name).split(/\s+/)[0] || name },
          { name: 'project', value: project },
        ],
        displayName: selectedTemplate.name,
      });
      sendingAction.current = false;
      if (ok) {
        setSelectedTemplate(null);
        setDraft('');
        fetchInbox({ silent: true, skip: 0 });
      }
      return;
    }
    if (!draft.trim()) return;
    sendingAction.current = true;
    const ok = await sendText(draft);
    sendingAction.current = false;
    if (ok) {
      setDraft('');
      fetchInbox({ silent: true, skip: 0 });
    }
  };

  const runTemplateAction = async (label, fn) => {
    if (!selected?.lead_id || sendingAction.current) return;
    sendingAction.current = true;
    try {
      const res = await fn(selected.lead_id);
      if (res.data?.success) {
        toast.success(`${label} sent`);
        await sync();
        fetchInbox({ silent: true, skip: 0 });
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

  const onListScroll = (e) => {
    const el = e.currentTarget;
    if (loadingMore || !hasMore || listLoading) return;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 80) {
      fetchInbox({ append: true, skip: conversations.length, silent: true });
    }
  };

  const openCreateLead = () => {
    setCreateForm({
      first_name: '',
      last_name: '',
      phone: selected?.phone || selected?.peer_phone || '',
      project: '',
      lead_source: 'WhatsApp',
    });
    setCreateOpen(true);
  };

  const submitCreateLead = async (e) => {
    e.preventDefault();
    if (!createForm.first_name.trim() || !createForm.phone.trim()) {
      toast.error('Name and phone are required');
      return;
    }
    setCreateSubmitting(true);
    try {
      const created = await leadsAPI.create({
        first_name: createForm.first_name.trim(),
        last_name: createForm.last_name.trim() || '',
        phone: createForm.phone.trim(),
        project: createForm.project || undefined,
        lead_source: createForm.lead_source || 'WhatsApp',
        lead_status: 'New',
      });
      const lead = created?.data;
      toast.success('Lead created');
      setCreateOpen(false);
      await fetchInbox({ skip: 0 });
      if (lead?.id) {
        await openLeadChat(lead);
      }
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to create lead');
    } finally {
      setCreateSubmitting(false);
    }
  };

  const displayLead = leadDetail || selected;
  const displayName =
    selected?.is_unmatched && !leadDetail
      ? 'Unknown'
      : selected?.display_name ||
        `${displayLead?.first_name || ''} ${displayLead?.last_name || ''}`.trim() ||
        displayLead?.phone ||
        'Conversation';

  const effectiveSessionOpen = selected?.session_open || sessionOpen;
  const composerBlocked = !effectiveSessionOpen && !selectedTemplate;

  return (
    <div className="h-[calc(100vh-5.5rem)] min-h-[480px] flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3 shrink-0">
        <div>
          <h1 className="font-serif text-2xl text-crm-fg flex items-center gap-2">
            <MessageCircle className="text-green-500" size={24} />
            WhatsApp
          </h1>
          <p className="text-crm-fg-muted text-sm mt-0.5">
            Team inbox — search any lead to start a chat, reply in place
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => fetchInbox({ skip: 0 })}
          disabled={listLoading}
          className="border-crm-border text-crm-fg-secondary hover:text-crm-fg hover:bg-white/5"
        >
          {listLoading ? (
            <Loader2 size={14} className="animate-spin mr-1.5" />
          ) : (
            <RefreshCw size={14} className="mr-1.5" />
          )}
          Refresh
        </Button>
      </div>

      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[300px_minmax(0,1fr)_260px] gap-3">
        {/* Conversation list */}
        <aside
          className={`bg-crm-elevated border border-crm-border rounded-xl flex flex-col min-h-0 ${
            mobilePane === 'list' ? 'flex' : 'hidden lg:flex'
          }`}
        >
          <div className="p-3 border-b border-crm-border space-y-2" ref={searchWrapRef}>
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-crm-fg-muted" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onFocus={() => leadHits.length && setShowLeadDropdown(true)}
                placeholder="Search chats or any lead"
                className="w-full h-10 pl-9 pr-3 rounded-lg bg-crm-muted border border-crm-border text-sm text-crm-fg placeholder:text-crm-fg-muted focus:border-green-500/60 outline-none"
              />
              {showLeadDropdown && debouncedQuery.length >= 2 && (
                <div className="absolute z-20 left-0 right-0 mt-1 rounded-lg border border-crm-border bg-crm-elevated shadow-xl max-h-64 overflow-y-auto">
                  <p className="px-3 py-1.5 text-[10px] uppercase tracking-wider text-crm-fg-muted border-b border-white/5">
                    Start chat with…
                  </p>
                  {leadSearchLoading ? (
                    <div className="flex items-center gap-2 px-3 py-3 text-xs text-crm-fg-muted">
                      <Loader2 size={12} className="animate-spin" /> Searching leads…
                    </div>
                  ) : leadHits.length === 0 ? (
                    <p className="px-3 py-3 text-xs text-crm-fg-muted">No matching leads</p>
                  ) : (
                    leadHits.map((lead) => (
                      <button
                        key={lead.id}
                        type="button"
                        onClick={() => openLeadChat(lead)}
                        className="w-full text-left px-3 py-2.5 hover:bg-white/5 border-b border-white/5 last:border-0"
                      >
                        <p className="text-sm text-crm-fg truncate">{leadDisplayName(lead)}</p>
                        <p className="text-[11px] text-crm-fg-secondary truncate">
                          {lead.phone || '—'}
                          {lead.project ? ` · ${lead.project}` : ''}
                        </p>
                      </button>
                    ))
                  )}
                </div>
              )}
            </div>
            <div className="flex gap-1">
              {FILTERS.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  onClick={() => setListFilter(f.id)}
                  className={`flex-1 h-8 rounded-md text-xs transition-colors ${
                    listFilter === f.id
                      ? 'bg-green-600/20 text-green-400 border border-green-500/40'
                      : 'text-crm-fg-secondary border border-crm-border hover:bg-white/5'
                  }`}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto" ref={listRef} onScroll={onListScroll}>
            {listLoading && !conversations.length ? (
              <div className="flex items-center justify-center py-16 text-crm-fg-muted">
                <Loader2 className="animate-spin mr-2" size={18} />
                Loading…
              </div>
            ) : listError ? (
              <div className="p-6 text-center text-sm text-red-400">{listError}</div>
            ) : conversations.length === 0 ? (
              <div className="p-8 text-center text-crm-fg-muted text-sm">
                <MessageCircle className="mx-auto mb-2 opacity-50" size={32} />
                {debouncedQuery
                  ? 'No conversations match — try Start chat with a lead above'
                  : listFilter === 'unread'
                    ? 'No unread conversations'
                    : listFilter === 'mine'
                      ? 'No conversations on your leads'
                      : 'No WhatsApp conversations yet'}
              </div>
            ) : (
              <>
                {conversations.map((c) => {
                  const key = conversationKeyOf(c);
                  const active = key === selectedKey;
                  const unread = Number(c.unread_count || 0);
                  return (
                    <button
                      key={key}
                      type="button"
                      onClick={() => selectConversation(key)}
                      className={`w-full text-left px-3 py-3 border-b border-white/5 transition-colors ${
                        active ? 'bg-green-500/10' : 'hover:bg-white/5'
                      }`}
                    >
                      <div className="flex gap-3">
                        <div className="relative h-10 w-10 shrink-0">
                          <div
                            className={`h-10 w-10 rounded-full flex items-center justify-center text-xs font-semibold ${
                              c.is_unmatched
                                ? 'bg-amber-600/20 text-amber-300'
                                : 'bg-green-600/20 text-green-400'
                            }`}
                          >
                            {c.is_unmatched ? '?' : initials(c.display_name)}
                          </div>
                          {unread > 0 && (
                            <span className="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-green-500 text-[10px] text-black font-semibold flex items-center justify-center">
                              {unread > 9 ? '9+' : unread}
                            </span>
                          )}
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-start justify-between gap-2">
                            <p
                              className={`text-sm truncate ${
                                unread > 0 ? 'text-crm-fg font-semibold' : 'text-crm-fg font-medium'
                              }`}
                            >
                              {c.display_name}
                            </p>
                            <span className="text-[10px] text-crm-fg-muted shrink-0">
                              {relativeTime(c.last_message_at)}
                            </span>
                          </div>
                          <p
                            className={`text-xs truncate mt-0.5 ${
                              unread > 0 ? 'text-crm-fg/90 font-medium' : 'text-crm-fg-secondary'
                            }`}
                          >
                            {c.last_message_preview || '—'}
                          </p>
                          <div className="flex items-center gap-1.5 mt-1 text-[10px] text-green-500/90">
                            <MessageCircle size={10} />
                            <span className="truncate">
                              {c.is_unmatched
                                ? c.phone || 'Unknown number'
                                : c.project || c.phone || 'WhatsApp'}
                            </span>
                          </div>
                        </div>
                      </div>
                    </button>
                  );
                })}
                {loadingMore && (
                  <div className="flex justify-center py-3 text-crm-fg-muted">
                    <Loader2 className="animate-spin" size={16} />
                  </div>
                )}
              </>
            )}
          </div>
        </aside>

        {/* Chat thread */}
        <section
          className={`bg-crm-elevated border border-crm-border rounded-xl flex flex-col min-h-0 ${
            mobilePane === 'chat' ? 'flex' : 'hidden lg:flex'
          }`}
        >
          {!selectedKey ? (
            <div className="flex-1 flex items-center justify-center text-crm-fg-muted text-sm p-8">
              Select a conversation
            </div>
          ) : (
            <>
              <div className="px-4 py-3 border-b border-crm-border flex items-start justify-between gap-3 shrink-0">
                <div className="min-w-0">
                  <button
                    type="button"
                    className="lg:hidden text-xs text-crm-fg-secondary mb-1"
                    onClick={() => setMobilePane('list')}
                  >
                    ← Conversations
                  </button>
                  <h2 className="text-crm-fg font-medium truncate">{displayName}</h2>
                  <p className="text-xs text-crm-fg-muted truncate">
                    {selected?.phone || selected?.peer_phone}
                    {selected?.is_unmatched ? ' · Not in CRM' : ''}
                  </p>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {selected?.is_unmatched && (
                    <Button
                      type="button"
                      size="sm"
                      className="h-8 bg-amber-600/20 text-amber-300 hover:bg-amber-600/30 border border-amber-500/30"
                      onClick={openCreateLead}
                    >
                      <UserPlus size={14} className="mr-1" />
                      Create Lead
                    </Button>
                  )}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="lg:hidden text-crm-fg-secondary"
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
                    className="border-crm-border text-crm-fg-secondary hover:text-crm-fg"
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
                  <div className="flex justify-center py-16 text-crm-fg-muted">
                    <Loader2 className="animate-spin" size={20} />
                  </div>
                ) : messages.length === 0 ? (
                  <div className="text-center py-16 text-crm-fg-muted">
                    <MessageCircle className="mx-auto mb-3 opacity-50" size={36} />
                    <p>No messages yet</p>
                    <p className="text-xs mt-1 max-w-xs mx-auto">
                      Send a template to start the conversation (required outside the 24h window).
                    </p>
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

              <div className="border-t border-crm-border p-3 space-y-2 shrink-0">
                {!effectiveSessionOpen && (
                  <div className="text-xs text-amber-300/90 bg-amber-900/20 border border-amber-500/20 rounded-lg px-3 py-2">
                    Outside 24h window — send a template to message this customer.
                  </div>
                )}
                {waTemplatesLoaded && waTemplates.length > 0 && (
                  <select
                    value={selectedTemplate?.name || ''}
                    onChange={(e) => {
                      const tpl = waTemplates.find((t) => t.name === e.target.value) || null;
                      setSelectedTemplate(tpl);
                      if (tpl) setDraft('');
                    }}
                    className="w-full h-9 px-3 rounded-lg bg-crm-muted border border-crm-border text-xs text-crm-fg focus:border-green-500 outline-none"
                  >
                    <option value="">— Free text (session) —</option>
                    {waTemplates.map((t) => (
                      <option key={t.id || t.name} value={t.name}>
                        {t.name}
                      </option>
                    ))}
                  </select>
                )}
                {selected?.lead_id && (
                  <div className="flex flex-wrap gap-1.5">
                    {[
                      { key: 'melange', label: 'Mélange' },
                      { key: 'reserve-16', label: 'Reserve 16' },
                      { key: 'krsna', label: 'Krsna' },
                      { key: 'vivriti', label: 'Vivriti' },
                    ].map((p) => (
                      <Button
                        key={p.key}
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs border-crm-border text-crm-fg-secondary"
                        onClick={() =>
                          runTemplateAction(`${p.label} brochure`, (id) =>
                            whatsappAPI.sendBrochure(id, p.key)
                          )
                        }
                      >
                        {p.label}
                      </Button>
                    ))}
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs border-crm-border text-crm-fg-secondary"
                      onClick={() => runTemplateAction('Pricing', whatsappAPI.sendPricing)}
                    >
                      Pricing
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      className="h-7 text-xs border-crm-border text-crm-fg-secondary"
                      onClick={() =>
                        runTemplateAction('Site visit request', whatsappAPI.sendSiteVisitRequest)
                      }
                    >
                      Site visit
                    </Button>
                  </div>
                )}
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
                    placeholder={
                      selectedTemplate
                        ? `Send template: ${selectedTemplate.name}`
                        : effectiveSessionOpen
                          ? 'Type a message...'
                          : 'Select a template above…'
                    }
                    disabled={composerBlocked && !selectedTemplate}
                    className="flex-1 h-11 px-4 bg-crm-muted border border-crm-border rounded-full text-crm-fg text-sm placeholder:text-crm-fg-muted focus:border-green-500 outline-none disabled:opacity-50"
                  />
                  <Button
                    type="button"
                    onClick={handleSend}
                    disabled={
                      sending ||
                      (selectedTemplate ? false : !draft.trim() || composerBlocked)
                    }
                    className="h-11 w-11 rounded-full bg-green-600 hover:bg-green-700 text-white text-on-brand p-0 disabled:opacity-50"
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
          className={`bg-crm-elevated border border-crm-border rounded-xl flex flex-col min-h-0 ${
            mobilePane === 'props' ? 'flex' : 'hidden lg:flex'
          }`}
        >
          <div className="px-4 py-3 border-b border-crm-border shrink-0">
            <button
              type="button"
              className="lg:hidden text-xs text-crm-fg-secondary mb-2"
              onClick={() => setMobilePane('chat')}
            >
              ← Chat
            </button>
            <h3 className="text-sm font-medium text-crm-fg">
              {selected?.is_unmatched ? 'Unknown number' : 'Lead details'}
            </h3>
            <p className="text-[11px] text-crm-fg-muted mt-0.5">
              {selected?.is_unmatched ? 'Create a CRM lead to link this chat' : 'CRM fields'}
            </p>
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {!selectedKey ? (
              <p className="text-sm text-crm-fg-muted">No conversation selected</p>
            ) : selected?.is_unmatched ? (
              <>
                <div className="flex items-center gap-3">
                  <div className="h-12 w-12 rounded-full bg-amber-600/20 text-amber-300 flex items-center justify-center text-sm font-semibold">
                    ?
                  </div>
                  <div className="min-w-0">
                    <p className="text-crm-fg font-medium">Unknown</p>
                    <p className="text-xs text-crm-fg-secondary flex items-center gap-1 truncate">
                      <Phone size={11} />
                      {selected.phone || selected.peer_phone}
                    </p>
                  </div>
                </div>
                <Button
                  type="button"
                  className="w-full bg-amber-600/20 text-amber-200 hover:bg-amber-600/30 border border-amber-500/30"
                  onClick={openCreateLead}
                >
                  <Plus size={14} className="mr-2" />
                  Create Lead
                </Button>
              </>
            ) : leadLoading && !displayLead ? (
              <div className="flex justify-center py-10 text-crm-fg-muted">
                <Loader2 className="animate-spin" size={18} />
              </div>
            ) : (
              <>
                <div className="flex items-center gap-3">
                  <div className="h-12 w-12 rounded-full bg-white/5 text-[#C5A059] flex items-center justify-center text-sm font-semibold">
                    {initials(displayName)}
                  </div>
                  <div className="min-w-0">
                    <p className="text-crm-fg font-medium truncate">{displayName}</p>
                    <p className="text-xs text-crm-fg-secondary flex items-center gap-1 truncate">
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
                  value={displayLead?.status || displayLead?.pipeline_status || displayLead?.lead_status}
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
                {selected?.lead_id && (
                  <div className="space-y-2 mt-2">
                    <Button
                      type="button"
                      className="w-full bg-[#C5A059]/15 text-[#C5A059] hover:bg-[#C5A059]/25 border border-[#C5A059]/30"
                      onClick={() => navigate(`/lead/${selected.lead_id}#lead-overview`)}
                    >
                      <ExternalLink size={14} className="mr-2" />
                      Open Lead Overview
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      className="w-full border-crm-border text-crm-fg-secondary hover:text-crm-fg hover:bg-white/5"
                      onClick={() => navigate(`/lead/${selected.lead_id}`)}
                    >
                      <ExternalLink size={14} className="mr-2" />
                      Open Digital Twin
                    </Button>
                  </div>
                )}
              </>
            )}
          </div>
        </aside>
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="bg-crm-elevated border-crm-border text-crm-fg max-w-md">
          <DialogHeader>
            <DialogTitle className="font-serif text-xl flex items-center gap-2">
              <UserPlus className="text-amber-400" size={22} />
              Create lead from WhatsApp
            </DialogTitle>
          </DialogHeader>
          <form onSubmit={submitCreateLead} className="space-y-3">
            <div>
              <label className="text-[11px] uppercase text-crm-fg-muted">First name *</label>
              <input
                className="mt-1 w-full h-10 px-3 rounded-lg bg-crm-muted border border-crm-border text-sm"
                value={createForm.first_name}
                onChange={(e) => setCreateForm((f) => ({ ...f, first_name: e.target.value }))}
                required
              />
            </div>
            <div>
              <label className="text-[11px] uppercase text-crm-fg-muted">Last name</label>
              <input
                className="mt-1 w-full h-10 px-3 rounded-lg bg-crm-muted border border-crm-border text-sm"
                value={createForm.last_name}
                onChange={(e) => setCreateForm((f) => ({ ...f, last_name: e.target.value }))}
              />
            </div>
            <div>
              <label className="text-[11px] uppercase text-crm-fg-muted">Phone *</label>
              <input
                className="mt-1 w-full h-10 px-3 rounded-lg bg-crm-muted border border-crm-border text-sm"
                value={createForm.phone}
                onChange={(e) => setCreateForm((f) => ({ ...f, phone: e.target.value }))}
                required
              />
            </div>
            <div>
              <label className="text-[11px] uppercase text-crm-fg-muted">Project</label>
              <select
                className="mt-1 w-full h-10 px-3 rounded-lg bg-crm-muted border border-crm-border text-sm"
                value={createForm.project}
                onChange={(e) => setCreateForm((f) => ({ ...f, project: e.target.value }))}
              >
                <option value="">— Select —</option>
                {CANONICAL_PROJECTS.filter((p) => p !== 'All projects').map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>
            <Button
              type="submit"
              disabled={createSubmitting}
              className="w-full bg-green-600 hover:bg-green-700 text-white text-on-brand"
            >
              {createSubmitting ? (
                <Loader2 size={16} className="animate-spin mr-2" />
              ) : null}
              Create & open chat
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default WhatsAppInboxPage;