import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { platformOpsAPI } from '../services/api';
import { useAuth } from '../context/AuthContext';
import { toast } from 'sonner';
import { Activity, RefreshCw } from 'lucide-react';
import { CrmBadge } from '../components/ui/CrmBadge';
import { Button } from '../components/ui/button';

const POLL_MS = 30_000;

const PRESENCE_VARIANT = {
  online: 'success',
  offline: 'neutral',
};

const PRESENCE_LABEL = {
  online: 'Online',
  offline: 'Offline',
};

const OpsActiveStatusPage = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [reps, setReps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadReps = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    else setRefreshing(true);
    try {
      const { data } = await platformOpsAPI.getRepActivity();
      setReps(data || []);
    } catch {
      toast.error('Failed to load rep activity');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    if (!user?.is_platform_operator) {
      navigate('/dashboard', { replace: true });
      return undefined;
    }
    loadReps();
    const timer = setInterval(() => loadReps(true), POLL_MS);
    return () => clearInterval(timer);
  }, [user, navigate, loadReps]);

  if (!user?.is_platform_operator) {
    return null;
  }

  const withinHours =
    typeof reps[0]?.within_business_hours === 'boolean'
      ? reps[0].within_business_hours
      : reps.some((r) => r.within_business_hours);
  const hoursLabel = reps[0]?.business_hours_label || 'Mon–Sat 10:00–17:30 IST';

  return (
    <div className="space-y-3 max-w-6xl" data-testid="ops-active-status-page">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-[#C5A059]/10 flex items-center justify-center">
            <Activity size={20} className="text-[#C5A059]" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-foreground">Active Status</h1>
            <p className="text-muted-foreground text-sm">
              Online = on duty today (IST). Beat = last CRM heartbeat (~1 min while the tab is open).
            </p>
          </div>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => loadReps(true)}
          disabled={refreshing}
          className="gap-2"
        >
          <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
          Refresh
        </Button>
      </div>

      {typeof withinHours === 'boolean' && (
        <div className="text-sm text-muted-foreground space-y-1">
          <div>
            Business hours:{' '}
            <span className="text-foreground">{hoursLabel}</span>{' '}
            <CrmBadge variant={withinHours ? 'success' : 'neutral'}>
              {withinHours ? 'Open now' : 'Closed now'}
            </CrmBadge>
          </div>
          <p className="text-xs">
            SLA auto-routing runs only during business hours and only for users who logged in or
            sent a beat today (IST). Stale beats do not pause SLA the same day. JWT session lasts
            ~12 hours (re-login needed for the app, not for duty). Page refreshes every 30s.
          </p>
        </div>
      )}

      {loading ? (
        <div className="text-[#C5A059] animate-pulse py-12 text-center">Loading team...</div>
      ) : (
        <div className="bg-card border border-border rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-muted-foreground text-left">
                  <th className="px-4 py-3 font-medium">Name</th>
                  <th className="px-4 py-3 font-medium">Role</th>
                  <th className="px-4 py-3 font-medium">Presence</th>
                  <th className="px-4 py-3 font-medium">Last login</th>
                  <th className="px-4 py-3 font-medium">Beat</th>
                  <th className="px-4 py-3 font-medium">SLA pause</th>
                  <th className="px-4 py-3 font-medium">Open New</th>
                </tr>
              </thead>
              <tbody>
                {reps.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                      No active reps or admins found
                    </td>
                  </tr>
                ) : (
                  reps.map((rep) => (
                    <tr key={rep.id} className="border-b border-border/60 hover:bg-muted/30 align-top">
                      <td className="px-4 py-3">
                        <div className="font-medium text-foreground">{rep.full_name}</div>
                        <div className="text-xs text-muted-foreground">{rep.email || '—'}</div>
                      </td>
                      <td className="px-4 py-3">
                        <CrmBadge variant={rep.role === 'admin' ? 'warning' : 'neutral'}>
                          {rep.role === 'admin' ? 'Admin' : 'Rep'}
                        </CrmBadge>
                      </td>
                      <td className="px-4 py-3">
                        <CrmBadge variant={PRESENCE_VARIANT[rep.presence] || 'neutral'}>
                          {PRESENCE_LABEL[rep.presence] || rep.presence}
                        </CrmBadge>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground whitespace-nowrap">
                        {formatRelativeMinutes(
                          rep.minutes_since_login ?? rep.minutes_since_active
                        )}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground whitespace-nowrap tabular-nums">
                        {formatBeat(rep.seconds_since_beat, rep.minutes_since_beat)}
                      </td>
                      <td className="px-4 py-3 max-w-[280px]">
                        <div className="flex flex-col gap-0.5">
                          <CrmBadge variant={rep.sla_paused || !rep.routing_eligible ? 'warning' : 'success'}>
                            {rep.sla_pause_label ||
                              (rep.routing_eligible ? 'Eligible' : 'Not eligible')}
                          </CrmBadge>
                          {rep.sla_pause_detail && (
                            <span className="text-xs text-muted-foreground leading-snug">
                              {rep.sla_pause_detail}
                            </span>
                          )}
                          {rep.sla_pause_until && rep.sla_paused && (
                            <span className="text-xs text-foreground/80">
                              Until: {rep.sla_pause_until}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-foreground tabular-nums">
                        {rep.open_new_leads ?? 0}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

function formatRelativeMinutes(minutes) {
  if (minutes == null) return '—';
  if (minutes <= 0) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

/** Prefer seconds for fresh heartbeats so 30s poll / 1min beat is visible. */
function formatBeat(seconds, minutes) {
  if (seconds == null && minutes == null) return '—';
  if (seconds != null) {
    if (seconds < 5) return 'Just now';
    if (seconds < 60) return `${seconds}s ago`;
    const mins = Math.floor(seconds / 60);
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  }
  return formatRelativeMinutes(minutes);
}

export default OpsActiveStatusPage;
