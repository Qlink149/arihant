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
  idle: 'warning',
  offline: 'neutral',
};

const PRESENCE_LABEL = {
  online: 'Online',
  idle: 'Idle',
  offline: 'Offline',
};

const ROUTING_REASON_LABEL = {
  account_inactive: 'Account disabled',
  outside_business_hours: 'Outside business hours',
  manual_on_break: 'Manual status (break / away)',
  no_recent_heartbeat: 'No recent heartbeat',
};

function formatLastActive(minutes) {
  if (minutes == null) return '—';
  if (minutes <= 0) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

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

  const withinHours = reps.some((r) => r.within_business_hours) || reps[0]?.within_business_hours;

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
              Live rep presence and SLA routing eligibility (30m reassign engine)
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
        <div className="text-sm text-muted-foreground">
          Business hours (IST):{' '}
          <CrmBadge variant={withinHours ? 'success' : 'neutral'}>
            {withinHours ? 'Open' : 'Closed'}
          </CrmBadge>
        </div>
      )}

      {loading ? (
        <div className="text-[#C5A059] animate-pulse py-12 text-center">Loading reps...</div>
      ) : (
        <div className="bg-card border border-border rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-muted-foreground text-left">
                  <th className="px-4 py-3 font-medium">Name</th>
                  <th className="px-4 py-3 font-medium">Email</th>
                  <th className="px-4 py-3 font-medium">Presence</th>
                  <th className="px-4 py-3 font-medium">Manual status</th>
                  <th className="px-4 py-3 font-medium">Last active</th>
                  <th className="px-4 py-3 font-medium">SLA routing</th>
                  <th className="px-4 py-3 font-medium">Open New</th>
                </tr>
              </thead>
              <tbody>
                {reps.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                      No reps found
                    </td>
                  </tr>
                ) : (
                  reps.map((rep) => (
                    <tr key={rep.id} className="border-b border-border/60 hover:bg-muted/30">
                      <td className="px-4 py-3 font-medium text-foreground">{rep.full_name}</td>
                      <td className="px-4 py-3 text-muted-foreground">{rep.email || '—'}</td>
                      <td className="px-4 py-3">
                        <CrmBadge variant={PRESENCE_VARIANT[rep.presence] || 'neutral'}>
                          {PRESENCE_LABEL[rep.presence] || rep.presence}
                        </CrmBadge>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground capitalize">
                        {rep.manual_status ? rep.manual_status.replace(/_/g, ' ') : '—'}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {formatLastActive(rep.minutes_since_active)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-col gap-0.5">
                          <CrmBadge variant={rep.routing_eligible ? 'success' : 'warning'}>
                            {rep.routing_eligible ? 'Eligible' : 'Not eligible'}
                          </CrmBadge>
                          {!rep.routing_eligible && rep.routing_ineligible_reason && (
                            <span className="text-xs text-muted-foreground">
                              {ROUTING_REASON_LABEL[rep.routing_ineligible_reason] || rep.routing_ineligible_reason}
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

export default OpsActiveStatusPage;
