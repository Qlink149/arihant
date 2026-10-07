import React, { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { AlertTriangle, Clock, Loader2, RefreshCw } from 'lucide-react';
import { metaAdsAPI } from '../../services/api';

const POLL_MS = 3000;
const POLL_TIMEOUT_MS = 6 * 60 * 1000;

// Last-synced line, token/error banners and the admin "Sync now" button.
// Sync runs server-side in the background; we poll /last-sync until the lock
// is released and a newer log row exists, then ask the parent to refetch.
export function MetaSyncStatus({ lastSync, onLastSync, onSynced }) {
  const [syncing, setSyncing] = useState(false);
  const timer = useRef(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  const running = syncing || Boolean(lastSync?.running);

  const poll = useCallback((prevStartedAt, startedAtMs) => {
    timer.current = setTimeout(async () => {
      if (!alive.current) return;
      try {
        const { data } = await metaAdsAPI.getLastSync();
        if (!alive.current) return;
        onLastSync(data);
        const finished = !data.running && data.started_at && data.started_at !== prevStartedAt;
        if (finished) {
          setSyncing(false);
          if (data.status === 'error') toast.error('Meta Ads sync failed');
          else toast.success('Meta Ads synced');
          onSynced();
          return;
        }
      } catch {
        /* transient - keep polling until timeout */
      }
      if (Date.now() - startedAtMs > POLL_TIMEOUT_MS) {
        setSyncing(false);
        toast.error('Sync is taking longer than expected - check back shortly');
        return;
      }
      poll(prevStartedAt, startedAtMs);
    }, POLL_MS);
  }, [onLastSync, onSynced]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      const { data } = await metaAdsAPI.syncNow();
      if (data?.reason === 'not_configured') {
        toast.error('Meta Ads is not configured on the server');
        setSyncing(false);
        return;
      }
      if (data?.reason === 'already_running') toast.info('A sync is already running');
      else toast.info('Sync started - this takes about a minute');
      poll(lastSync?.started_at || null, Date.now());
    } catch (e) {
      setSyncing(false);
      toast.error(e?.response?.status === 403 ? 'Only admins can sync' : 'Could not start the sync');
    }
  };

  return (
    <>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-xs text-crm-fg-muted" data-testid="meta-ads-last-sync">
          <Clock size={14} />
          {running
            ? 'Sync in progress…'
            : lastSync?.started_at
              ? `Last synced: ${new Date(lastSync.started_at).toLocaleString('en-IN')}`
              : 'Never synced yet'}
        </div>
        <button
          type="button"
          onClick={handleSync}
          disabled={running}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium bg-[#C5A059]/15 text-[#C5A059] hover:bg-[#C5A059]/25 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
          data-testid="meta-ads-sync-now"
        >
          {running ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
          {running ? 'Syncing…' : 'Sync now'}
        </button>
      </div>

      {lastSync?.token_expiring_soon && (
        <div
          className="flex items-center gap-2 bg-amber-500/10 border border-amber-500/30 rounded-lg px-3 py-2 text-amber-400 text-xs"
          data-testid="meta-ads-token-warning"
        >
          <AlertTriangle size={14} />
          The Meta Ads access token is expiring soon — it needs to be refreshed to keep this data flowing.
        </div>
      )}

      {lastSync?.status === 'error' && !running && (
        <div
          className="flex items-center gap-2 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2 text-red-400 text-xs"
          data-testid="meta-ads-sync-error"
        >
          <AlertTriangle size={14} />
          The last sync failed: {lastSync.error_message || 'unknown error'}
        </div>
      )}
    </>
  );
}

export default MetaSyncStatus;
