import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { whatsappAPI } from '../../services/api';
import { parseApiDate } from '../../utils/datetime';

function sortChatAscending(messages) {
  const list = [...(messages || [])];
  list.sort(
    (a, b) =>
      (parseApiDate(a.created_at)?.getTime() ?? 0) -
      (parseApiDate(b.created_at)?.getTime() ?? 0)
  );
  return list;
}

/**
 * Load / sync / send WhatsApp thread for a lead or unmatched peer phone
 * (shared by Digital Twin + Inbox).
 *
 * Pass leadId for CRM leads, or phone alone for Unknown / unmatched threads.
 */
export function useLeadWhatsAppThread(leadId, { phone, autoLoad = true } = {}) {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [sending, setSending] = useState(false);
  const [sessionOpen, setSessionOpen] = useState(false);
  const [error, setError] = useState(null);

  const hasThread = Boolean(leadId || phone);

  const load = useCallback(
    async ({ withSync = true } = {}) => {
      if (!leadId && !phone) return [];
      setLoading(true);
      setError(null);
      try {
        let localMessages = [];
        if (leadId) {
          const response = await whatsappAPI.getLeadChat(leadId);
          localMessages = sortChatAscending(response.data.messages || []);
          if (typeof response.data.session_open === 'boolean') {
            setSessionOpen(response.data.session_open);
          }
        } else {
          const response = await whatsappAPI.getChatHistory(phone);
          localMessages = sortChatAscending(response.data.messages || []);
          if (typeof response.data.session_open === 'boolean') {
            setSessionOpen(response.data.session_open);
          }
        }
        setMessages(localMessages);

        if (withSync) {
          setSyncing(true);
          try {
            const synced = leadId
              ? await whatsappAPI.syncLeadChat(leadId)
              : await whatsappAPI.syncChatHistory(phone);
            const next = sortChatAscending(synced.data.messages || []);
            setMessages(next);
            if (typeof synced.data.session_open === 'boolean') {
              setSessionOpen(synced.data.session_open);
            }
            return next;
          } catch (syncErr) {
            console.warn('WhatsApp background sync skipped:', syncErr);
            return localMessages;
          } finally {
            setSyncing(false);
          }
        }
        return localMessages;
      } catch (err) {
        console.error('Failed to fetch chat history:', err);
        setError(err);
        toast.error('Failed to load chat history');
        return [];
      } finally {
        setLoading(false);
      }
    },
    [leadId, phone]
  );

  const sync = useCallback(async () => {
    if (!leadId && !phone) return;
    setSyncing(true);
    try {
      const res = leadId
        ? await whatsappAPI.syncLeadChat(leadId)
        : await whatsappAPI.syncChatHistory(phone);
      setMessages(sortChatAscending(res.data.messages || []));
      if (typeof res.data.session_open === 'boolean') {
        setSessionOpen(res.data.session_open);
      }
      const n = res.data.synced ?? 0;
      toast.success(
        n ? `Synced ${n} message${n === 1 ? '' : 's'} from WhatsApp` : 'Chat up to date'
      );
    } catch (err) {
      console.error('Failed to sync chat:', err);
      toast.error('Failed to sync from WhatsApp');
    } finally {
      setSyncing(false);
    }
  }, [leadId, phone]);

  const sendText = useCallback(
    async (text) => {
      const body = (text || '').trim();
      if (!body || (!leadId && !phone)) return false;
      setSending(true);
      try {
        let response;
        if (leadId) {
          response = await whatsappAPI.sendToLead(leadId, {
            destination: phone || undefined,
            message_type: 'text',
            text: body,
          });
        } else {
          response = await whatsappAPI.sendMessage({
            destination: phone,
            message_type: 'text',
            text: body,
          });
        }
        if (response.data.success) {
          toast.success('Message sent');
          await load({ withSync: false });
          load({ withSync: true });
          return true;
        }
        toast.error('Message not sent', {
          description: response.data.error || 'Failed to send message',
        });
        return false;
      } catch (err) {
        const detail =
          err?.response?.data?.error ||
          err?.response?.data?.detail ||
          'Network or server error. Please try again.';
        toast.error('Message not sent', { description: String(detail) });
        return false;
      } finally {
        setSending(false);
      }
    },
    [leadId, phone, load]
  );

  const sendTemplate = useCallback(
    async ({ templateName, templateParameters, displayName } = {}) => {
      if (!templateName || (!leadId && !phone)) return false;
      setSending(true);
      try {
        const payload = {
          destination: phone || undefined,
          message_type: 'template',
          template_name: templateName,
          template_parameters: templateParameters,
          broadcast_name: 'arihant_crm',
        };
        const response = leadId
          ? await whatsappAPI.sendToLead(leadId, payload)
          : await whatsappAPI.sendMessage({ ...payload, destination: phone });
        if (response.data.success) {
          toast.success(`${displayName || 'Template'} sent`);
          await load({ withSync: false });
          load({ withSync: true });
          return true;
        }
        toast.error('Template not sent', {
          description: response.data.error || 'Failed to send template',
        });
        return false;
      } catch (err) {
        const detail =
          err?.response?.data?.error ||
          err?.response?.data?.detail ||
          'Network or server error. Please try again.';
        toast.error('Template not sent', { description: String(detail) });
        return false;
      } finally {
        setSending(false);
      }
    },
    [leadId, phone, load]
  );

  useEffect(() => {
    if (!autoLoad || !hasThread) {
      setMessages([]);
      setSessionOpen(false);
      return undefined;
    }
    load({ withSync: true });
    return undefined;
  }, [autoLoad, hasThread, leadId, phone, load]);

  return {
    messages,
    loading,
    syncing,
    sending,
    sessionOpen,
    error,
    load,
    sync,
    sendText,
    sendTemplate,
    setMessages,
  };
}
