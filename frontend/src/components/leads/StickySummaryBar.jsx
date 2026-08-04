import React, { memo } from 'react';
import { Bot, MessageCircle, Phone } from 'lucide-react';
import { Button } from '../ui/button';
import { LeadAvatar } from './LeadAvatar';
import { TemperatureBadge } from './TemperatureBadge';
import { isNurturingStatus } from '../../utils/nurtureLabel';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '../ui/tooltip';

export const StickySummaryBar = memo(function StickySummaryBar({
  lead,
  visible,
  onWhatsApp,
  onAICall,
}) {
  if (!visible || !lead) return null;

  const assigneeName =
    lead.assigned_to || lead.assigned_to_name || lead.presales_agent || 'Unassigned';

  return (
    <div
      className="sticky-summary-bar sticky top-[6.5rem] z-20 flex items-center gap-3 px-3 py-2 min-h-[var(--header-height-compact)] max-h-[90px] backdrop-blur-md"
      data-testid="lead-sticky-summary-bar"
    >
      <LeadAvatar lead={lead} size="sm" />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 min-w-0">
          <p className="text-crm-fg font-medium text-sm truncate">
            {lead.first_name} {lead.last_name}
          </p>
          {isNurturingStatus(lead.lead_status) && (
            <TemperatureBadge temperature={lead.temperature} />
          )}
        </div>
        <p className="text-crm-fg-muted text-xs truncate">{assigneeName}</p>
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="h-8 w-8 text-crm-fg-muted hover:text-green-400"
              onClick={onWhatsApp}
              aria-label="WhatsApp"
            >
              <MessageCircle size={16} />
            </Button>
          </TooltipTrigger>
          <TooltipContent className="bg-crm-elevated border-crm-border text-crm-fg">
            WhatsApp
          </TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="h-8 w-8 text-crm-fg-muted hover:text-[#C5A059]"
              onClick={onAICall}
              aria-label="AI call"
            >
              <Phone size={16} />
            </Button>
          </TooltipTrigger>
          <TooltipContent className="bg-crm-elevated border-crm-border text-crm-fg">
            AI call
          </TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="h-8 w-8 text-crm-fg-muted hover:text-[#C5A059]"
              aria-label="AI insights"
            >
              <Bot size={16} />
            </Button>
          </TooltipTrigger>
          <TooltipContent className="bg-crm-elevated border-crm-border text-crm-fg">
            AI insights
          </TooltipContent>
        </Tooltip>
      </div>
    </div>
  );
});

export default StickySummaryBar;
