import React from 'react';
import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react';
import {
  TONE_CLASS, deltaTone, formatCompact, formatDelta, formatINR, formatPct,
} from '../../utils/metaAdsFormat';
import { rangeDays } from '../../utils/metaAdsPeriod';

const CARDS = [
  { key: 'spend', label: 'Spend', fmt: (v) => formatCompact(v, { rupee: true }) },
  { key: 'leads', label: 'Leads (Meta)', fmt: (v) => formatCompact(v) },
  { key: 'cpl', label: 'Cost / lead', fmt: (v) => formatINR(v) },
  { key: 'impressions', label: 'Impressions', fmt: (v) => formatCompact(v) },
  { key: 'clicks', label: 'Clicks', fmt: (v) => formatCompact(v) },
  { key: 'ctr', label: 'CTR', fmt: (v) => formatPct(v) },
  { key: 'cpm', label: 'CPM', fmt: (v) => formatINR(v) },
];

function Delta({ metric, delta, days }) {
  const tone = deltaTone(metric, delta);
  const Icon = delta > 0 ? ArrowUpRight : delta < 0 ? ArrowDownRight : Minus;
  return (
    <span
      className={`inline-flex items-center gap-0.5 text-[11px] ${TONE_CLASS[tone]}`}
      title={`Change vs the previous ${days} days`}
      data-testid={`meta-kpi-delta-${metric}`}
    >
      <Icon size={12} />
      {formatDelta(delta)}
    </span>
  );
}

export function MetaKpiCards({ overview }) {
  const { current, deltas, date_from: from, date_to: to } = overview;
  const days = rangeDays(from, to);
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-3" data-testid="meta-kpis">
      {CARDS.map((c) => (
        <div
          key={c.key}
          className="bg-crm-muted/40 border border-white/5 rounded-lg p-3"
          data-testid={`meta-kpi-${c.key}`}
        >
          <p className="text-crm-fg-muted text-xs">{c.label}</p>
          <p className="text-white text-lg font-semibold mt-0.5" data-testid={`meta-kpi-value-${c.key}`}>
            {c.fmt(current?.[c.key])}
          </p>
          <Delta metric={c.key} delta={deltas?.[c.key]} days={days} />
        </div>
      ))}
    </div>
  );
}

export default MetaKpiCards;
