import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Bell, ArrowLeft, AlertTriangle, Phone, Calendar, Clock, Loader2 } from 'lucide-react';
import { notificationsAPI, unwrapNotificationsPayload } from '../services/api';
import { Button } from '../components/ui/button';
import { CrmBadge } from '../components/ui/CrmBadge';
import { toast } from 'sonner';
import { useMarkAllNotificationsRead } from '../hooks/useMarkAllNotificationsRead';

const PAGE_SIZE = 40;

const NotificationsPage = () => {
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [total, setTotal] = useState(0);

  const load = useCallback(async ({ append = false, skip = 0 } = {}) => {
    if (append) setLoadingMore(true);
    else setLoading(true);
    try {
      const { data } = await notificationsAPI.getAll({
        unread_only: false,
        skip,
        limit: PAGE_SIZE,
      });
      const { notifications, has_more, total: t } = unwrapNotificationsPayload(data);
      setItems((prev) => (append ? [...prev, ...notifications] : notifications));
      setHasMore(has_more);
      setTotal(t);
    } catch (e) {
      toast.error('Failed to load notifications');
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, []);

  useEffect(() => {
    load({ skip: 0 });
  }, [load]);

  const { markAllRead: markAll, busy: markAllBusy } = useMarkAllNotificationsRead({
    getItems: () => items,
    setItems,
    refetch: () => load({ skip: 0 }),
  });

  const markOne = async (id) => {
    try {
      await notificationsAPI.markRead(id);
      setItems((prev) =>
        prev.map((n) => (n.id === id ? { ...n, is_read: true } : n))
      );
    } catch (e) {
      toast.error('Could not update notification');
    }
  };

  const iconFor = (type) => {
    if (type === 'rnr_followup') return Phone;
    if (type === 'dormant_lead' || type === 'stale_lead') return Clock;
    if (type?.includes('task')) return Calendar;
    return AlertTriangle;
  };

  return (
    <div className="space-y-3 max-w-3xl mx-auto" data-testid="notifications-page">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => navigate(-1)} className="text-crm-fg-secondary">
            <ArrowLeft size={18} />
          </Button>
          <div>
            <h1 className="font-serif text-2xl text-crm-fg flex items-center gap-2">
              <Bell className="text-[#C5A059]" size={24} />
              Notifications
            </h1>
            <p className="text-crm-fg-muted text-sm mt-1">
              Full alert history{total ? ` · ${total} total` : ''}
            </p>
          </div>
        </div>
        {items.some((n) => !n.is_read) && (
          <Button
            size="sm"
            variant="outline"
            onClick={markAll}
            disabled={markAllBusy}
            className="border-[#C5A059]/40 text-[#C5A059]"
            data-testid="notifications-mark-all"
          >
            {markAllBusy ? 'Clearing…' : 'Mark all read'}
          </Button>
        )}
      </div>

      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="glass-card rounded-lg p-4 animate-pulse h-20 bg-white/5" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="glass-card rounded-lg p-12 text-center text-crm-fg-muted">No notifications</div>
      ) : (
        <div className="space-y-2">
          {items.map((n) => {
            const Icon = iconFor(n.type || n.notification_type);
            const unread = !n.is_read;
            return (
              <motion.div
                key={n.id}
                layout
                data-testid={`notification-row-${n.id}`}
                data-read={unread ? 'false' : 'true'}
                className={`glass-card rounded-lg p-4 flex gap-3 cursor-pointer border ${
                  unread
                    ? 'border-[#C5A059]/40 bg-[#C5A059]/10'
                    : 'border-white/5 opacity-70'
                }`}
                onClick={() => {
                  if (unread) markOne(n.id);
                  if (n.lead_id) navigate(`/lead/${n.lead_id}`);
                }}
              >
                <div
                  className={`w-10 h-10 rounded-full flex items-center justify-center flex-shrink-0 ${
                    unread ? 'bg-[#C5A059]/20' : 'bg-white/10'
                  }`}
                >
                  <Icon size={18} className={unread ? 'text-[#C5A059]' : 'text-crm-fg-muted'} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className={`text-sm truncate ${unread ? 'text-crm-fg font-semibold' : 'text-crm-fg-secondary font-medium'}`}>
                      {n.title || n.lead_name}
                    </p>
                    {unread ? (
                      <CrmBadge variant="gold" size="xs">
                        Unread
                      </CrmBadge>
                    ) : (
                      <span className="text-[10px] text-crm-fg-muted uppercase tracking-wide">Read</span>
                    )}
                  </div>
                  <p className="text-crm-fg-secondary text-xs mt-1">{n.message}</p>
                  <div className="flex flex-wrap gap-2 mt-2">
                    {n.is_auto && <span className="text-[10px] text-crm-fg-muted">Auto alert</span>}
                    {n.is_overdue && (
                      <CrmBadge variant="danger" size="xs" uppercase>
                        Overdue
                      </CrmBadge>
                    )}
                  </div>
                </div>
              </motion.div>
            );
          })}
          {hasMore && (
            <div className="flex justify-center pt-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={loadingMore}
                className="border-crm-border text-crm-fg-secondary"
                data-testid="notifications-load-more"
                onClick={() => load({ append: true, skip: items.length })}
              >
                {loadingMore ? (
                  <>
                    <Loader2 size={14} className="animate-spin mr-2" /> Loading…
                  </>
                ) : (
                  'Load more'
                )}
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default NotificationsPage;
