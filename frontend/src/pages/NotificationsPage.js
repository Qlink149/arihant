import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Bell, ArrowLeft, AlertTriangle, Phone, Calendar, Clock } from 'lucide-react';
import { notificationsAPI } from '../services/api';
import { Button } from '../components/ui/button';
import { toast } from 'sonner';

const NotificationsPage = () => {
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await notificationsAPI.getAll();
      setItems(data || []);
    } catch (e) {
      toast.error('Failed to load notifications');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const markAll = async () => {
    try {
      await notificationsAPI.markAllRead();
      await load();
      toast.success('All alerts cleared');
    } catch (e) {
      toast.error('Could not mark all as read');
    }
  };

  const markOne = async (id) => {
    try {
      await notificationsAPI.markRead(id);
      setItems((prev) => prev.map((n) => (n.id === id ? { ...n, is_read: true } : n)));
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
    <div className="space-y-6 max-w-3xl mx-auto">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="sm" onClick={() => navigate(-1)} className="text-[#A1A1AA]">
            <ArrowLeft size={18} />
          </Button>
          <div>
            <h1 className="font-serif text-2xl text-white flex items-center gap-2">
              <Bell className="text-[#C5A059]" size={24} />
              Notifications
            </h1>
            <p className="text-[#52525B] text-sm mt-1">System alerts and reminders</p>
          </div>
        </div>
        {items.some((n) => !n.is_read) && (
          <Button size="sm" variant="outline" onClick={markAll} className="border-[#C5A059]/40 text-[#C5A059]">
            Mark all read
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
        <div className="glass-card rounded-lg p-12 text-center text-[#52525B]">No notifications</div>
      ) : (
        <div className="space-y-2">
          {items.map((n) => {
            const Icon = iconFor(n.type);
            return (
              <motion.div
                key={n.id}
                layout
                className={`glass-card rounded-lg p-4 flex gap-3 cursor-pointer border ${
                  !n.is_read ? 'border-[#C5A059]/30 bg-[#C5A059]/5' : 'border-white/5'
                }`}
                onClick={() => {
                  markOne(n.id);
                  if (n.lead_id) navigate(`/lead/${n.lead_id}`);
                }}
              >
                <div className="w-10 h-10 rounded-full bg-white/10 flex items-center justify-center flex-shrink-0">
                  <Icon size={18} className="text-[#C5A059]" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-white font-medium text-sm">{n.title || n.lead_name}</p>
                  <p className="text-[#A1A1AA] text-xs mt-1">{n.message}</p>
                  {n.is_auto && <span className="text-[10px] text-[#52525B] mt-2 inline-block">Auto alert</span>}
                </div>
                {!n.is_read && <span className="w-2 h-2 rounded-full bg-[#C5A059] flex-shrink-0 mt-2" />}
              </motion.div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default NotificationsPage;
