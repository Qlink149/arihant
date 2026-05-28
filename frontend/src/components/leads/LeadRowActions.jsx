import React from 'react';
import { StickyNote } from 'lucide-react';
import { Button } from '../ui/button';

export function LeadRowActions({ leadId, onNote }) {
  return (
    <div className="flex items-center justify-end gap-1" onClick={(e) => e.stopPropagation()}>
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
