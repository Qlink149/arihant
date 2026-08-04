import React, { memo } from 'react';
import { getAccentStyle } from '../../utils/leadOverview';

export const LeadOverviewCard = memo(function LeadOverviewCard({ metric, onClick }) {
  const { bar, Icon, iconClass } = getAccentStyle(metric);
  const count = metric?.count ?? 0;
  const label = metric?.label ?? '';
  const subtitle = metric?.subtitle ?? '';

  return (
    <button
      type="button"
      onClick={() => onClick?.(metric)}
      aria-label={`${label}: ${count}. ${subtitle}`}
      data-testid={`lead-overview-${metric?.key || 'metric'}`}
      className="flex flex-col h-full text-left w-full bg-crm-elevated border border-crm-border rounded-md p-3 card-hover hover:border-[#C5A059]/40 hover:bg-white/5 transition-colors cursor-pointer focus:outline-none focus-visible:ring-1 focus-visible:ring-[#C5A059]/50"
    >
      <div className="flex items-start gap-2 mb-2">
        <span className={`w-1 h-6 shrink-0 rounded-sm ${bar}`} aria-hidden />
        <span
          className="w-7 h-7 shrink-0 flex items-center justify-center border border-crm-border rounded-sm bg-black/30"
        >
          <Icon size={14} className={iconClass} aria-hidden />
        </span>
      </div>
      <p className="text-xs uppercase tracking-wide text-crm-fg-secondary leading-tight">{label}</p>
      <p className="text-2xl font-semibold text-white tabular-nums mt-0.5">{count}</p>
      <p className="text-[10px] text-crm-fg-muted mt-auto pt-1">{subtitle}</p>
    </button>
  );
});

export default LeadOverviewCard;
