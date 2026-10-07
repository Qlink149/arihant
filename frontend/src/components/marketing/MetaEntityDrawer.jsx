import React, { useEffect, useState } from 'react';
import {
  Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { metaAdsAPI } from '../../services/api';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '../ui/sheet';
import {
  formatINR, formatInt, formatPct, statusLabel,
} from '../../utils/metaAdsFormat';

const LEVEL_LABEL = { campaign: 'Campaign', adset: 'Ad set', ad: 'Ad' };

// Per-day detail for one campaign / ad set / ad. This is the only place
// reach and frequency are shown: only a single day's value is exact (they
// are unique-person counts, so they cannot be summed across days or levels).
export function MetaEntityDrawer({ target, dateFrom, dateTo, onClose }) {
  const [state, setState] = useState({ loading: false, error: false, data: null });

  useEffect(() => {
    if (!target) return undefined;
    let cancelled = false;
    setState({ loading: true, error: false, data: null });
    metaAdsAPI
      .getEntityDaily(target.level, target.entity_id, { date_from: dateFrom, date_to: dateTo })
      .then((res) => { if (!cancelled) setState({ loading: false, error: false, data: res.data }); })
      .catch(() => { if (!cancelled) setState({ loading: false, error: true, data: null }); });
    return () => { cancelled = true; };
  }, [target, dateFrom, dateTo]);

  const days = state.data?.days || [];
  const entity = state.data?.entity;

  return (
    <Sheet open={Boolean(target)} onOpenChange={(open) => { if (!open) onClose(); }}>
      <SheetContent side="right" className="w-full sm:max-w-2xl overflow-y-auto bg-crm-elevated border-white/10 text-white" data-testid="meta-entity-drawer">
        <SheetHeader>
          <SheetTitle className="text-white text-base pr-6 break-words">{target?.name || target?.entity_id}</SheetTitle>
          <SheetDescription className="text-crm-fg-muted text-xs">
            {target ? LEVEL_LABEL[target.level] : ''} · ID {target?.entity_id}
            {entity?.effective_status ? ` · ${statusLabel(entity.effective_status)}` : ''}
            {entity?.objective ? ` · ${entity.objective}` : ''}
            {entity?.creative_id ? ` · Creative ${entity.creative_id}` : ''}
          </SheetDescription>
        </SheetHeader>

        {state.loading && <div className="text-crm-fg-muted text-sm py-8 text-center">Loading daily data…</div>}
        {state.error && <div className="text-red-400 text-sm py-8 text-center">Could not load daily data.</div>}

        {state.data && days.length === 0 && (
          <div className="text-crm-fg-muted text-sm py-8 text-center" data-testid="meta-drawer-empty">
            No activity for this {LEVEL_LABEL[target.level].toLowerCase()} between {dateFrom} and {dateTo}.
          </div>
        )}

        {days.length > 0 && (
          <div className="mt-4 space-y-4">
            <ResponsiveContainer width="100%" height={180}>
              <ComposedChart data={days} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="date" tickFormatter={(d) => d.slice(5)} stroke="#52525B" tick={{ fill: '#A1A1AA', fontSize: 10 }} minTickGap={14} />
                <YAxis yAxisId="left" stroke="#52525B" tick={{ fill: '#A1A1AA', fontSize: 10 }} />
                <YAxis yAxisId="right" orientation="right" stroke="#52525B" tick={{ fill: '#A1A1AA', fontSize: 10 }} />
                <Tooltip contentStyle={{ background: '#18181B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, fontSize: 12 }} />
                <Bar yAxisId="left" dataKey="spend" name="Spend (₹)" fill="#1877F2" radius={[3, 3, 0, 0]} />
                <Line yAxisId="right" dataKey="leads" name="Leads" stroke="#10B981" strokeWidth={2} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>

            <div className="overflow-x-auto" data-testid="meta-drawer-table">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-crm-border text-crm-fg-muted">
                    {['Date', 'Spend', 'Leads', 'CPL', 'Impr.', 'Clicks', 'CTR', 'Reach', 'Freq.'].map((h, i) => (
                      <th key={h} className={`py-2 px-2 font-medium ${i === 0 ? 'text-left' : 'text-right'}`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[...days].reverse().map((d) => (
                    <tr key={d.date} className="border-b border-white/5" data-testid={`meta-drawer-day-${d.date}`}>
                      <td className="py-1.5 px-2 text-white">{d.date}</td>
                      <td className="py-1.5 px-2 text-right text-crm-fg-secondary">{formatINR(d.spend)}</td>
                      <td className="py-1.5 px-2 text-right text-crm-fg-secondary">{formatInt(d.leads)}</td>
                      <td className="py-1.5 px-2 text-right text-crm-fg-secondary">{formatINR(d.cpl)}</td>
                      <td className="py-1.5 px-2 text-right text-crm-fg-secondary">{formatInt(d.impressions)}</td>
                      <td className="py-1.5 px-2 text-right text-crm-fg-secondary">{formatInt(d.clicks)}</td>
                      <td className="py-1.5 px-2 text-right text-crm-fg-secondary">{formatPct(d.ctr)}</td>
                      <td className="py-1.5 px-2 text-right text-crm-fg-secondary">{formatInt(d.reach)}</td>
                      <td className="py-1.5 px-2 text-right text-crm-fg-secondary">{d.frequency ? Number(d.frequency).toFixed(2) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-crm-fg-muted text-[11px]">
              Reach and frequency count unique people, so they are shown per day only — adding days or ad sets together would overstate them.
            </p>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

export default MetaEntityDrawer;
