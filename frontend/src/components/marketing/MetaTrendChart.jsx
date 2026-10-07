import React, { useMemo, useState } from 'react';
import {
  Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { formatCompact, formatINR, formatInt } from '../../utils/metaAdsFormat';

const MODES = {
  spend_leads: {
    label: 'Spend & leads',
    left: { key: 'spend', name: 'Spend (₹)', color: '#1877F2', fmt: (v) => formatINR(v) },
    right: { key: 'leads', name: 'Leads', color: '#10B981', fmt: (v) => formatInt(v) },
  },
  cpl: {
    label: 'Cost / lead',
    left: { key: 'cpl', name: 'Cost per lead (₹)', color: '#C5A059', fmt: (v) => formatINR(v) },
    right: null,
  },
  reach: {
    label: 'Impressions & clicks',
    left: { key: 'impressions', name: 'Impressions', color: '#8B5CF6', fmt: (v) => formatInt(v) },
    right: { key: 'clicks', name: 'Clicks', color: '#F59E0B', fmt: (v) => formatInt(v) },
  },
};

const shortDate = (d) => (d ? d.slice(5) : '');

export function MetaTrendChart({ series }) {
  const [mode, setMode] = useState('spend_leads');
  const cfg = MODES[mode];
  // Days with no CPL (no leads) would plot as 0 and look like a "free" day;
  // keep them as gaps instead.
  const data = useMemo(() => series.map((d) => ({ ...d, cpl: d.cpl ?? null })), [series]);
  const hasData = series.some((d) => d.spend > 0 || d.impressions > 0);
  // Meta data can lag or stop (paused account, expired token): say so instead
  // of letting a trailing run of zero days read as "spend collapsed".
  const lastDataDay = [...series].reverse().find((d) => d.spend > 0 || d.impressions > 0)?.date;
  const lastDay = series.length ? series[series.length - 1].date : null;
  const gapDays = lastDataDay && lastDay ? Math.round((Date.parse(lastDay) - Date.parse(lastDataDay)) / 86400000) : 0;

  return (
    <div data-testid="meta-trend">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-white text-sm font-medium">Daily trend</h4>
        <div className="flex gap-1.5">
          {Object.entries(MODES).map(([k, m]) => (
            <button
              key={k}
              type="button"
              onClick={() => setMode(k)}
              className={`px-2.5 py-1 rounded-md text-xs transition-colors ${
                mode === k ? 'bg-[#C5A059]/20 text-[#C5A059]' : 'bg-white/5 text-crm-fg-muted hover:text-crm-fg-secondary'
              }`}
              data-testid={`meta-trend-mode-${k}`}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>
      {!hasData ? (
        <div className="text-crm-fg-muted text-sm py-10 text-center" data-testid="meta-trend-empty">
          No activity in this range.
        </div>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis dataKey="date" tickFormatter={shortDate} stroke="#52525B" tick={{ fill: '#A1A1AA', fontSize: 10 }} minTickGap={16} />
              <YAxis yAxisId="left" stroke="#52525B" tick={{ fill: '#A1A1AA', fontSize: 11 }} tickFormatter={(v) => formatCompact(v)} />
              {cfg.right && (
                <YAxis yAxisId="right" orientation="right" stroke="#52525B" tick={{ fill: '#A1A1AA', fontSize: 11 }} tickFormatter={(v) => formatCompact(v)} />
              )}
              <Tooltip
                contentStyle={{ background: '#18181B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, fontSize: 12 }}
                labelStyle={{ color: '#C5A059' }}
                formatter={(value, name) => {
                  const col = [cfg.left, cfg.right].find((c) => c && c.name === name);
                  return [col ? col.fmt(value) : value, name];
                }}
              />
              <Bar yAxisId="left" dataKey={cfg.left.key} name={cfg.left.name} fill={cfg.left.color} radius={[3, 3, 0, 0]} />
              {cfg.right && (
                <Line yAxisId="right" dataKey={cfg.right.key} name={cfg.right.name} stroke={cfg.right.color} strokeWidth={2} dot={false} />
              )}
            </ComposedChart>
          </ResponsiveContainer>
          {gapDays >= 3 && (
            <p className="text-amber-400/90 text-xs text-center mt-1" data-testid="meta-trend-gap-note">
              Latest day with Meta data is {lastDataDay} — the last {gapDays} days in this range have no activity.
            </p>
          )}
          <div className="flex gap-4 justify-center mt-1" data-testid="meta-ads-chart-legend">
            <span className="flex items-center gap-1.5 text-xs text-crm-fg-secondary">
              <i className="w-3 h-3 rounded inline-block" style={{ background: cfg.left.color }} /> {cfg.left.name}
            </span>
            {cfg.right && (
              <span className="flex items-center gap-1.5 text-xs text-crm-fg-secondary">
                <i className="w-3 h-3 rounded inline-block" style={{ background: cfg.right.color }} /> {cfg.right.name}
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export default MetaTrendChart;
