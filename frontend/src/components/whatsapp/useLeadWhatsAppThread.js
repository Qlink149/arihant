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
 * Load / sync / send WhatsApp thread for a lead (shared by Digital Twin + Inbox).
 */
export function useLeadWhatsAppThread(leadId, { phone, autoLoad = true } = {}) {
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(
    async ({ withSync = true } = {}) => {
      if (!leadId) return [];
      setLoading(true);
      setError(null);
      try {
        const response = await whatsappAPI.getLeadChat(leadId);
        const localMessages = sortChatAscending(response.data.messages || []);
        setMessages(localMessages);

        if (withSync) {
          setSyncing(true);
          try {
            const synced = await whatsappAPI.syncLeadChat(leadId);
            const next = sortChatAscending(synced.data.messages || []);
            setMessages(next);
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
    [leadId]
  );

  const sync = useCallback(async () => {
    if (!leadId) return;
    setSyncing(true);
    try {
      const res = await whatsappAPI.syncLeadChat(leadId);
      setMessages(sortChatAscending(res.data.messages || []));
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
  }, [leadId]);

  const sendText = useCallback(
    async (text) => {
      const body = (text || '').trim();
      if (!leadId || !body) return false;
      setSending(true);
      try {
        const response = await whatsappAPI.sendToLead(leadId, {
          destination: phone || undefined,
          message_type: 'text',
          text: body,
        });
        if (response.data.success) {
          toast.success('Message sent');
          await load({ withSync: false });
          // Refresh from WATI in background
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

  useEffect(() => {
    if (!autoLoad || !leadId) {
      setMessages([]);
      return undefined;
    }
    load({ withSync: true });
    return undefined;
  }, [autoLoad, leadId, load]);

  return {
    messages,
    loading,
    syncing,
    sending,
    error,
    load,
    sync,
    sendText,
    setMessages,
  };
}
