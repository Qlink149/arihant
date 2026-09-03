import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { AlertTriangle, ExternalLink, Loader2, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { notificationsAPI } from '../services/api';
import { Button } from '../components/ui/button';
import { CrmBadge } from '../components/ui/CrmBadge';
import { parseApiDate, formatDateTimeIST } from '../utils/datetime';

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
    <div className="space-y-3" data-testid="escalation-queue-page">
      <motion.div
        initial={{ opacity: 0, y: -12 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col lg:flex-row lg:items-center justify-between gap-4"
      >
        <div>
          <h1
            className="text-xl font-semibold text-crm-fg flex items-center gap-2"
            data-testid="escalation-queue-title"
          >
            <AlertTriangle className="text-amber-400" size={22} />
            Escalation Queue
          </h1>
          <p className="text-crm-fg-secondary text-sm mt-1">
            {loading
              ? 'Loading escalations…'
              : rows.length
                ? `${rows.length} escalation${rows.length === 1 ? '' : 's'}`
                : 'No open escalations'}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label className="text-xs text-crm-fg-secondary flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={includeRead}
              onChange={(e) => setIncludeRead(e.target.checked)}
              data-testid="escalation-include-resolved"
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
            data-testid="escalation-refresh"
          >
            {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          </Button>
        </div>
      </motion.div>

      <div className="rounded-xl border border-crm-border bg-crm-elevated overflow-hidden">
        {loading && !rows.length ? (
          <div className="flex justify-center py-16 text-crm-fg-muted">
            <Loader2 className="animate-spin mr-2" size={18} /> Loading…
          </div>
        ) : rows.length === 0 ? (
          <div className="p-10 text-center text-crm-fg-muted text-sm" data-testid="escalation-empty">
            No open escalations
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm table-fixed min-w-[980px]" data-testid="escalation-table">
              <thead>
                <tr className="border-b border-crm-border text-left text-[11px] uppercase tracking-wider text-crm-fg-muted">
                  <th className="px-4 py-3 min-w-[180px]">Lead</th>
                  <th className="px-4 py-3 min-w-[200px]">Reason</th>
                  <th className="px-4 py-3 w-[120px]">Status</th>
                  <th className="px-4 py-3 w-[140px]">Assignee</th>
                  <th className="px-4 py-3 w-[120px]">Project</th>
                  <th className="px-4 py-3 w-[100px]">Age</th>
                  <th className="px-4 py-3 w-[160px] text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const open = !row.is_read;
                  const fired = row.fired_at_dt || row.created_at_dt || row.created_at;
                  return (
                    <tr
                      key={row.id}
                      className={`border-b border-white/5 hover:bg-white/[0.03] ${
                        open ? 'bg-amber-500/[0.04]' : 'opacity-75'
                      }`}
                      data-testid={`escalation-row-${row.id}`}
                    >
                      <td className="px-4 py-3">
                        <p className="text-crm-fg font-semibold truncate">{row.lead_name || 'Lead'}</p>
                        <p className="text-xs text-crm-fg-muted truncate">
                          {row.lead_phone || '—'}
                        </p>
                        {fired ? (
                          <p className="text-[10px] text-crm-fg-muted mt-0.5">
                            {formatDateTimeIST(fired)}
                          </p>
                        ) : null}
                      </td>
                      <td className="px-4 py-3 text-crm-fg-secondary">
                        <p className="line-clamp-2" title={row.title || row.message || ''}>
                          {row.title || row.message || 'Escalation'}
                        </p>
                      </td>
                      <td className="px-4 py-3">
                        {row.lead_status ? (
                          <CrmBadge variant="neutral" size="xs">
                            {row.lead_status}
                          </CrmBadge>
                        ) : (
                          <span className="text-crm-fg-muted">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-crm-fg-secondary truncate">
                        {row.lead_assignee || '—'}
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-crm-fg font-semibold truncate block">
                          {row.lead_project || '—'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-crm-fg-muted whitespace-nowrap">
                        {ageLabel(fired)}
                        {open ? (
                          <div className="mt-1">
                            <CrmBadge variant="warning" size="xs">
                              Open
                            </CrmBadge>
                          </div>
                        ) : null}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-2 justify-end">
                          {row.lead_id && (
                            <Button
                              type="button"
                              size="sm"
                              className="h-8 bg-[#C5A059] hover:bg-[#B8914A] text-white text-on-brand border-0"
                              onClick={() => navigate(`/lead/${row.lead_id}`)}
                              data-testid={`escalation-open-${row.id}`}
                            >
                              <ExternalLink size={12} className="mr-1" />
                              Open
                            </Button>
                          )}
                          {open && (
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              className="h-8 border-crm-border bg-crm-muted text-crm-fg hover:bg-crm-elevated"
                              disabled={busyId === row.id}
                              onClick={() => markResolved(row.id)}
                              data-testid={`escalation-resolve-${row.id}`}
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
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};

export default EscalationQueuePage;
