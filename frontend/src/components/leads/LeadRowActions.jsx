import React from 'react';
import { Bell, StickyNote } from 'lucide-react';
import { Button } from '../ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip';

export function LeadRowActions({ leadId, onNote, onNudge, canNudge, nudgeDisabled }) {
  return (
    <div className="flex items-center justify-end gap-1" onClick={(e) => e.stopPropagation()}>
      {canNudge ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <span>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="text-[#A1A1AA] hover:text-[#C5A059] h-8 w-8 p-0"
                onClick={() => onNudge?.(leadId)}
                disabled={nudgeDisabled}
                aria-label="Nudge assignee"
                data-testid={`nudge-lead-${leadId}`}
              >
                <Bell size={16} />
              </Button>
            </span>
          </TooltipTrigger>
          <TooltipContent className="bg-crm-elevated border border-crm-border text-crm-fg">
            {nudgeDisabled ? 'Assign a rep before nudging' : 'Nudge by Admin'}
          </TooltipContent>
        </Tooltip>
      ) : null}
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className="text-[#A1A1AA] hover:text-[#C5A059] h-8 w-8 p-0"
        onClick={() => onNote(leadId)}
        aria-label="Add note"
        data-testid={`note-lead-${leadId}`}
      >
        <StickyNote size={16} />
      </Button>
    </div>
  );
}

export default LeadRowActions;
