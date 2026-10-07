import React from 'react';
import { Info } from 'lucide-react';
import { formatCompact, formatInt, formatINR, formatPct } from '../../utils/metaAdsFormat';

const th = 'text-right text-crm-fg-muted font-medium py-2 px-3 whitespace-nowrap text-xs';

function Row({ r, bold = false }) {
  const cell = `py-2.5 px-3 text-right ${bold ? 'font-semibold text-white' : 'text-crm-fg-secondary'}`;
  return (
    <tr className={`border-b border-white/5 ${bold ? 'bg-white/[0.03]' : 'hover:bg-white/[0.02]'}`} data-testid={bold ? 'meta-funnel-total' : `meta-funnel-row-${r.project}`}>
      <td className={`py-2.5 px-3 text-left ${bold ? 'font-semibold' : 'font-medium'} text-white`}>{r.project}</td>
      <td className={cell}>{formatCompact(r.spend, { rupee: true })}</td>
      <td className={cell}>{formatInt(r.leads)}</td>
      <td className={cell}>{formatINR(r.cpl)}</td>
      <td className={`${cell} border-l border-white/5`}>{formatInt(r.crm_leads)}</td>
      <td className={cell}>{formatInt(r.crm_site_visits)}</td>
      <td className={cell}>{formatInt(r.crm_bookings)}</td>
      <td className={`${cell} border-l border-white/5`}>{formatINR(r.cost_per_crm_lead)}</td>
      <td className={cell}>{formatINR(r.cost_per_site_visit)}</td>
      <td className={cell}>{formatINR(r.cost_per_booking)}</td>
    </tr>
  );
}

// Meta spend/leads next to the CRM outcome cohort for the same date range.
export function MetaProjectFunnel({ funnel }) {
  const rows = funnel?.rows || [];
  const att = funnel?.attribution;
  if (!rows.length) return null;
  return (
    <div data-testid="meta-funnel">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-white text-sm font-medium">Project funnel — Meta spend vs CRM outcomes</h4>
      </div>
      <div className="flex items-start gap-2 bg-blue-500/5 border border-blue-500/20 rounded-lg px-3 py-2 text-xs text-blue-300/90 mb-3" data-testid="meta-funnel-note">
        <Info size={14} className="mt-0.5 flex-shrink-0" />
        <span>
          <strong>Meta leads</strong> are form fills as Meta counts them; <strong>CRM leads</strong> are Facebook/Instagram
          leads created in the CRM in the same dates. They are different numbers by design. Site visits and bookings are
          the <em>current</em> outcome of that CRM cohort, so recent leads are still maturing. Costs divide Meta spend by the CRM count.
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-crm-border">
              <th className="text-left text-crm-fg-muted font-medium py-2 px-3 text-xs">Project</th>
              <th className={th}>Spend</th>
              <th className={th}>Meta leads</th>
              <th className={th}>Meta CPL</th>
              <th className={`${th} border-l border-white/5`}>CRM leads</th>
              <th className={th}>Site visits</th>
              <th className={th}>Bookings</th>
              <th className={`${th} border-l border-white/5`}>₹ / CRM lead</th>
              <th className={th}>₹ / site visit</th>
              <th className={th}>₹ / booking</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => <Row key={r.project} r={r} />)}
            {funnel.totals && <Row r={funnel.totals} bold />}
          </tbody>
        </table>
      </div>
      {att && (
        <p className="text-crm-fg-muted text-xs mt-2" data-testid="meta-attribution">
          Campaign attribution: {att.coverage_pct == null ? '—' : formatPct(att.coverage_pct, 1)} of CRM Facebook/Instagram leads
          carry a campaign ID ({formatInt(att.with_campaign_id)} of {formatInt(att.crm_meta_leads)}).
          {att.with_campaign_id === 0 && ' Per-campaign CRM outcomes will appear once the lead form sends campaign IDs.'}
        </p>
      )}
    </div>
  );
}

export default MetaProjectFunnel;
