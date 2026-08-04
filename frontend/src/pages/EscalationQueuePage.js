import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, ExternalLink, Loader2, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { notificationsAPI } from '../services/api';
import { Button } from '../components/ui/button';
import { parseApiDate } from '../utils/datetime';

function ageLabel(value) {
  const d = parseApiDate(value);
  if (!d) return '';
  const sec = Math.round((Date.now() - d.getTime()) / 1000);
  if (sec < 60) return 'just now';
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 48) return `${hr}h ago`;
  return `${Math.floor(hr / 24)}d ago`;
}

const EscalationQueuePage = () => {
  const navigate = useNavigate();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [includeRead, setIncludeRead] = useState(false);
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await notificationsAPI.getEscalations({
        unread_only: !includeRead,
        limit: 100,
      });
      setRows(res.data?.escalations || []);
    } catch (err) {
      console.error(err);
      toast.error('Failed to load escalation queue');
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [includeRead]);

  useEffect(() => {
    load();
  }, [load]);

  const markResolved = async (id) => {
    if (!id) return;
    setBusyId(id);
    try {
      await notificationsAPI.markRead(id);
      toast.success('Marked resolved');
      setRows((prev) => prev.filter((r) => r.id !== id));
    } catch {
      toast.error('Failed to mark resolved');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="font-serif text-2xl text-crm-fg flex items-center gap-2">
            <AlertTriangle className="text-amber-400" size={24} />
            Escalation Queue
          </h1>
          <p className="text-crm-fg-muted text-sm mt-1">
            Admin view of leads needing intervention — open, reassign from Digital Twin, then mark resolved.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-crm-fg-secondary flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={includeRead}
              onChange={(e) => setIncludeRead(e.target.checked)}
            />
            Include resolved
          </label>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={load}
            disabled={loading}
            className="border-crm-border text-crm-fg-secondary"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          </Button>
        </div>
      </div>

      <div className="rounded-xl border border-crm-border bg-crm-elevated overflow-hidden">
        {loading && !rows.length ? (
          <div className="flex justify-center py-16 text-crm-fg-muted">
            <Loader2 className="animate-spin mr-2" size={18} /> Loading…
          </div>
        ) : rows.length === 0 ? (
          <div className="p-10 text-center text-crm-fg-muted text-sm">No open escalations</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-crm-border text-left text-[11px] uppercase tracking-wider text-crm-fg-muted">
                  <th className="px-4 py-3">Lead</th>
                  <th className="px-4 py-3">Reason</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Assignee</th>
                  <th className="px-4 py-3">Age</th>
                  <th className="px-4 py-3">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="border-b border-white/5 hover:bg-white/[0.03]">
                    <td className="px-4 py-3">
                      <p className="text-crm-fg font-medium">{row.lead_name || 'Lead'}</p>
                      <p className="text-xs text-crm-fg-muted">
                        {row.lead_phone || '—'}
                        {row.lead_project ? ` · ${row.lead_project}` : ''}
                      </p>
                    </td>
                    <td className="px-4 py-3 text-crm-fg-secondary max-w-xs">
                      {row.title || row.message || 'Escalation'}
                    </td>
                    <td className="px-4 py-3 text-crm-fg-secondary">{row.lead_status || '—'}</td>
                    <td className="px-4 py-3 text-crm-fg-secondary">{row.lead_assignee || '—'}</td>
                    <td className="px-4 py-3 text-crm-fg-muted whitespace-nowrap">
                      {ageLabel(row.fired_at_dt || row.created_at_dt || row.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-2">
                        {row.lead_id && (
                          <Button
                            type="button"
                            size="sm"
                            className="h-8 bg-[#C5A059] hover:bg-[#B8914A] text-white text-on-brand border-0"
                            onClick={() => navigate(`/lead/${row.lead_id}`)}
                          >
                            <ExternalLink size={12} className="mr-1" />
                            Open
                          </Button>
                        )}
                        {!row.is_read && (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            className="h-8 border-crm-border bg-crm-muted text-crm-fg hover:bg-crm-elevated"
                            disabled={busyId === row.id}
                            onClick={() => markResolved(row.id)}
                          >
                            {busyId === row.id ? (
                              <Loader2 size={12} className="animate-spin" />
                            ) : (
                              'Resolve'
                            )}
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};

export default EscalationQueuePage;