import React, { memo, useMemo, useState } from 'react';
import { Crown, ListChecks } from 'lucide-react';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../ui/table';
import { LeadAvatar } from './LeadAvatar';
import { LeadStatusBadge } from './LeadStatusBadge';
import { LeadRowActions } from './LeadRowActions';
import { isNurturingStatus } from '../../utils/nurtureLabel';
import {
  formatFollowUp,
  getNurtureTemperatureTintClass,
  getOwnerDisplay,
  getRecentNote,
} from '../../utils/leadTable';

const RecentNoteCell = memo(function RecentNoteCell({ note, leadId }) {
  const [expanded, setExpanded] = useState(false);

  const normalized = useMemo(() => String(note || '').trim(), [note]);
  const isExpandable = useMemo(() => {
    if (!normalized) return false;
    return normalized.length > 140 || normalized.includes('\n');
  }, [normalized]);

  if (!normalized) {
    return <span className="text-[#52525B] text-sm">—</span>;
  }

  const toggle = (e) => {
    e.stopPropagation();
    setExpanded((v) => !v);
  };

  return (
    <div className="min-w-0">
      <div
        className={[
          'text-[#A1A1AA] text-sm break-words',
          expanded
            ? 'whitespace-pre-wrap max-h-80 overflow-y-auto rounded-md border border-white/10 bg-black/20 p-2'
            : 'line-clamp-2',
        ].join(' ')}
        title={!expanded ? normalized : undefined}
        data-testid={`lead-recent-note-${leadId}`}
        onClick={(e) => e.stopPropagation()}
      >
        {normalized}
      </div>

      {isExpandable && (
        <button
          type="button"
          onClick={toggle}
          className="mt-1 text-[11px] text-[#52525B] hover:text-[#C5A059] underline-offset-2 hover:underline"
          aria-expanded={expanded}
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  );
});

export function LeadDataTable({
  leads,
  loading,
  pendingTaskMap,
  pendingTasksList = [],
  onRowClick,
  onView,
  onNote,
}) {
  if (loading) {
    return (
      <div className="rounded-lg border border-white/5 bg-[#1A1A1A] overflow-hidden">
        <div className="p-8 space-y-3">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <div key={i} className="h-10 bg-white/5 rounded animate-pulse" />
          ))}
        </div>
      </div>
    );
  }

  if (!leads.length) {
    return (
      <div className="rounded-lg border border-white/5 bg-[#1A1A1A] p-12 text-center">
        <p className="text-[#A1A1AA]">No leads found</p>
        <p className="text-[#52525B] text-sm mt-1">Try adjusting your filters</p>
      </div>
    );
  }

  return (
    <div
      className="rounded-lg border border-white/5 bg-[#1A1A1A] overflow-x-auto"
      data-testid="lead-data-table"
    >
      <Table className="min-w-max w-full">
        <TableHeader>
          <TableRow className="border-white/10 hover:bg-transparent">
            <TableHead className="sticky top-0 z-10 bg-[#0A0A0A]/95 backdrop-blur text-[#52525B] text-xs uppercase tracking-wider min-w-[200px]">
              Name
            </TableHead>
            <TableHead className="sticky top-0 z-10 bg-[#0A0A0A]/95 backdrop-blur text-[#52525B] text-xs uppercase tracking-wider min-w-[120px]">
              Status
            </TableHead>
            <TableHead className="sticky top-0 z-10 bg-[#0A0A0A]/95 backdrop-blur text-[#52525B] text-xs uppercase tracking-wider min-w-[140px]">
              Next follow-up
            </TableHead>
            <TableHead className="sticky top-0 z-10 bg-[#0A0A0A]/95 backdrop-blur text-[#52525B] text-xs uppercase tracking-wider min-w-[100px]">
              Active tasks
            </TableHead>
            <TableHead className="sticky top-0 z-10 bg-[#0A0A0A]/95 backdrop-blur text-[#52525B] text-xs uppercase tracking-wider min-w-[160px]">
              Project
            </TableHead>
            <TableHead className="sticky top-0 z-10 bg-[#0A0A0A]/95 backdrop-blur text-[#52525B] text-xs uppercase tracking-wider min-w-[140px]">
              Sales owner
            </TableHead>
            <TableHead className="sticky top-0 z-10 bg-[#0A0A0A]/95 backdrop-blur text-[#52525B] text-xs uppercase tracking-wider min-w-[120px]">
              Source
            </TableHead>
            <TableHead className="sticky top-0 z-10 bg-[#0A0A0A]/95 backdrop-blur text-[#52525B] text-xs uppercase tracking-wider min-w-[220px] max-w-[320px]">
              Recent note
            </TableHead>
            <TableHead className="sticky top-0 z-10 bg-[#0A0A0A]/95 backdrop-blur text-[#52525B] text-xs uppercase tracking-wider w-[88px] text-right">
              Actions
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {leads.map((lead) => {
            const taskCount = pendingTaskMap?.get(lead.id) || 0;
            const followUp = formatFollowUp(lead, pendingTasksList, pendingTaskMap);
            const owner = getOwnerDisplay(lead);
            const recentNote = getRecentNote(lead);
            const t = (lead.temperature || '').trim();
            const isNurtureTemp = isNurturingStatus(lead.lead_status) && (t === 'Hot' || t === 'Warm');
            const tint = isNurtureTemp
              ? getNurtureTemperatureTintClass(lead.lead_status, t, { includeHover: true })
              : '';

            return (
              <TableRow
                key={lead.id}
                className={`border-white/5 cursor-pointer ${tint || 'hover:bg-white/5'}`}
                onClick={() => onRowClick(lead.id)}
                data-testid={`lead-row-${lead.id}`}
              >
                <TableCell className="py-2.5">
                  <div className="flex items-center gap-3 min-w-0">
                    <LeadAvatar lead={lead} size="md" />
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="text-white font-medium text-sm truncate">
                          {lead.first_name} {lead.last_name}
                        </span>
                        {lead.vip && (
                          <Crown className="text-purple-500 flex-shrink-0" size={14} aria-label="VIP" />
                        )}
                      </div>
                    </div>
                  </div>
                </TableCell>
                <TableCell className="py-2.5">
                  <LeadStatusBadge status={lead.lead_status} temperature={lead.temperature} />
                </TableCell>
                <TableCell className="py-2.5">
                  {followUp ? (
                    <span className="text-white text-sm font-medium">{followUp}</span>
                  ) : (
                    <span className="text-[#52525B] text-sm">—</span>
                  )}
                </TableCell>
                <TableCell className="py-2.5">
                  {taskCount > 0 ? (
                    <span className="inline-flex items-center gap-1.5 text-amber-400 text-sm">
                      <ListChecks size={14} />
                      <span className="bg-amber-500/20 text-amber-300 px-1.5 py-0.5 rounded-full text-xs font-medium">
                        {taskCount} pending
                      </span>
                    </span>
                  ) : (
                    <span className="text-[#52525B] text-sm">—</span>
                  )}
                </TableCell>
                <TableCell className="py-2.5 max-w-[200px]">
                  <span className="text-[#A1A1AA] text-sm truncate block" title={lead.project || ''}>
                    {lead.project || '—'}
                  </span>
                </TableCell>
                <TableCell className="py-2.5">
                  <div className="flex items-center gap-2 min-w-0">
                    {owner !== '—' && (
                      <LeadAvatar
                        lead={{ first_name: owner, last_name: '', id: owner }}
                        size="sm"
                      />
                    )}
                    <span className="text-[#A1A1AA] text-sm truncate" title={owner}>
                      {owner}
                    </span>
                  </div>
                </TableCell>
                <TableCell className="py-2.5 max-w-[140px]">
                  <span className="text-[#52525B] text-sm truncate block" title={lead.lead_source || ''}>
                    {lead.lead_source || '—'}
                  </span>
                </TableCell>
                <TableCell className="py-2.5 min-w-[220px] max-w-[320px]">
                  <RecentNoteCell note={recentNote} leadId={lead.id} />
                </TableCell>
                <TableCell className="py-2.5">
                  <LeadRowActions leadId={lead.id} onNote={onNote} />
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

export default LeadDataTable;
