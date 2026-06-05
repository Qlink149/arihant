import React, { memo } from 'react';
import { formatStatusDisplay } from '../../utils/nurtureLabel';

export const SalesDrilldownLeadRow = memo(function SalesDrilldownLeadRow({
  lead,
  formattedDate,
  onSelect,
}) {
  return (
    <div
      onClick={() => onSelect(lead.id)}
      className="flex items-center gap-3 p-3 rounded-lg bg-black/30 border border-white/5 hover:border-[#C5A059]/30 cursor-pointer transition-all group"
      data-testid={`drilldown-lead-${lead.id}`}
    >
      <div className="w-9 h-9 rounded-full bg-[#C5A059]/20 flex items-center justify-center text-[#C5A059] text-sm flex-shrink-0">
        {(lead.first_name || '?').charAt(0)}{(lead.last_name || '').charAt(0)}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-white text-sm font-medium truncate group-hover:text-[#C5A059] transition-colors">
          {lead.first_name} {lead.last_name}
        </p>
        <p className="text-[#52525B] text-xs truncate">{lead.project || 'No project'}</p>
      </div>
      <span className="text-[#A1A1AA] text-xs">
        {formatStatusDisplay(lead.lead_status, lead.temperature)}
      </span>
      <span className="text-[#52525B] text-[10px]">{formattedDate}</span>
    </div>
  );
});
