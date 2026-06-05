import React from 'react';
import { getAccentStyle } from '../../utils/leadOverview';

export function LeadOverviewCard({ metric, onClick }) {
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
      className="flex flex-col h-full min-h-[120px] text-left w-full bg-[#1A1A1A] border border-white/10 rounded-md p-4 card-hover hover:border-[#C5A059]/40 hover:bg-white/5 transition-colors cursor-pointer focus:outline-none focus-visible:ring-1 focus-visible:ring-[#C5A059]/50"
    >
      <div className="flex items-start gap-2 mb-3">
        <span className={`w-1 h-6 shrink-0 rounded-sm ${bar}`} aria-hidden />
        <span
          className="w-7 h-7 shrink-0 flex items-center justify-center border border-white/10 rounded-sm bg-black/30"
        >
          <Icon size={14} className={iconClass} aria-hidden />
        </span>
      </div>
      <p className="text-xs uppercase tracking-wide text-[#A1A1AA] leading-tight">{label}</p>
      <p className="text-3xl font-semibold text-white tabular-nums mt-1">{count}</p>
      <p className="text-xs text-[#52525B] mt-auto pt-2">{subtitle}</p>
    </button>
  );
}

export default LeadOverviewCard;
