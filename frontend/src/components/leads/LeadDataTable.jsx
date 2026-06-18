import React, { memo, useMemo, useState, useRef, useLayoutEffect, useCallback } from 'react';
import { useWindowVirtualizer } from '@tanstack/react-virtual';
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
import { CrmBadge } from '../ui/CrmBadge';
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip';
import {
  shouldUseVirtualList,
  getVirtualRowEstimate,
} from '../../constants/performanceFlags';

const COLUMN_COUNT = 9;

const LEAD_TABLE_COLUMNS = [200, 160, 148, 100, 160, 140, 120, 280, 88];

function LeadTableColGroup() {
  return (
    <colgroup>
      {LEAD_TABLE_COLUMNS.map((width, index) => (
        <col key={index} style={{ width }} />
      ))}
    </colgroup>
  );
}

const TABLE_LAYOUT_CLASS = 'table-fixed min-w-[1388px] w-full caption-bottom text-sm';

const RecentNoteCell = memo(function RecentNoteCell({ note, leadId, onResize }) {
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
    requestAnimationFrame(() => onResize?.());
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

const LeadTableRow = memo(function LeadTableRow({
  lead,
  taskCount,
  followUp,
  earliestTaskId,
  recentNote,
  tint,
  onRowClick,
  onNote,
  onOpenLeadTasks,
  onRowResize,
  density = 'comfortable',
  'data-index': dataIndex,
}) {
  const rowRef = useRef(null);
  const owner = getOwnerDisplay(lead);
  const fullName = `${lead.first_name || ''} ${lead.last_name || ''}`.trim();
  const cellPy = density === 'compact' ? 'py-1.5' : 'py-2.5';
  const textSize = density === 'compact' ? 'text-xs' : 'text-sm';
  const avatarSize = density === 'compact' ? 'sm' : 'md';

  const handleNoteResize = () => {
    requestAnimationFrame(() => onRowResize?.(rowRef.current));
  };

  return (
    <TableRow
      ref={rowRef}
      data-index={dataIndex}
      className={`border-white/5 cursor-pointer ${tint || 'hover:bg-white/5'}`}
      onClick={() => onRowClick(lead.id)}
      data-testid={`lead-row-${lead.id}`}
    >
      <TableCell className={`${cellPy} w-[200px] max-w-[200px] overflow-hidden`}>
        <div className={`flex items-center ${density === 'compact' ? 'gap-2' : 'gap-3'} min-w-0 w-full overflow-hidden`}>
          <div className="flex-shrink-0">
            <LeadAvatar lead={lead} size={avatarSize} />
          </div>
          <div className="min-w-0 flex-1 overflow-hidden">
            <div className="flex items-center gap-1.5 min-w-0 overflow-hidden">
              <span
                className={`text-white font-medium ${textSize} truncate`}
                title={fullName || undefined}
              >
                {lead.first_name} {lead.last_name}
              </span>
              {lead.vip && (
                <Crown className="text-purple-500 flex-shrink-0" size={14} aria-label="VIP" />
              )}
            </div>
          </div>
        </div>
      </TableCell>
      <TableCell className={`${cellPy} w-[160px] max-w-[160px] min-w-0 overflow-hidden`}>
        <div className="min-w-0 max-w-full">
          <LeadStatusBadge status={lead.lead_status} temperature={lead.temperature} />
        </div>
      </TableCell>
      <TableCell className={`${cellPy} w-[148px] max-w-[148px] min-w-0 overflow-hidden`}>
        {followUp ? (
          <button
            type="button"
            className={`text-white ${textSize} font-medium hover:text-[#C5A059] underline-offset-2 hover:underline truncate block max-w-full text-left`}
            onClick={(e) => {
              e.stopPropagation();
              onOpenLeadTasks?.(lead, { highlightTaskId: earliestTaskId || null });
            }}
            title={followUp}
            data-testid={`lead-followup-${lead.id}`}
          >
            {followUp}
          </button>
        ) : (
          <span className={`text-[#52525B] ${textSize}`}>—</span>
        )}
      </TableCell>
      <TableCell className={cellPy}>
        {taskCount > 0 ? (
          <button
            type="button"
            className={`inline-flex items-center gap-1.5 text-amber-400 ${textSize} hover:text-[#C5A059]`}
            onClick={(e) => {
              e.stopPropagation();
              onOpenLeadTasks?.(lead, { highlightTaskId: null });
            }}
            title="Click to view pending tasks"
            data-testid={`lead-active-tasks-${lead.id}`}
          >
            <ListChecks size={14} />
            <CrmBadge variant="warning" size="xs">
              {taskCount} pending
            </CrmBadge>
          </button>
        ) : (
          <span className={`text-[#52525B] ${textSize}`}>—</span>
        )}
      </TableCell>
      <TableCell className={`${cellPy} max-w-[200px]`}>
        <span className={`text-[#A1A1AA] ${textSize} truncate block`} title={lead.project || ''}>
          {lead.project || '—'}
        </span>
      </TableCell>
      <TableCell className={cellPy}>
        <div className="flex items-center gap-2 min-w-0">
          {owner !== '—' && (
            <LeadAvatar lead={{ first_name: owner, last_name: '', id: owner }} size="sm" />
          )}
          <span className={`text-[#A1A1AA] ${textSize} truncate`} title={owner}>
            {owner}
          </span>
        </div>
      </TableCell>
      <TableCell className={`${cellPy} max-w-[140px]`}>
        <span className={`text-[#52525B] ${textSize} truncate block`} title={lead.lead_source || ''}>
          {lead.lead_source || '—'}
        </span>
      </TableCell>
      <TableCell className={`${cellPy} overflow-hidden`}>
        <RecentNoteCell note={recentNote} leadId={lead.id} onResize={handleNoteResize} />
      </TableCell>
      <TableCell className={cellPy}>
        <LeadRowActions leadId={lead.id} onNote={onNote} />
      </TableCell>
    </TableRow>
  );
});

function LeadTableHeader() {
  return (
    <TableHeader>
      <TableRow className="border-white/10 hover:bg-transparent">
        <TableHead className="sticky top-0 z-10 bg-[#0A0A0A]/95 backdrop-blur text-[#52525B] text-xs uppercase tracking-wider min-w-[200px]">
          Name
        </TableHead>
        <TableHead className="sticky top-0 z-10 bg-[#0A0A0A]/95 backdrop-blur text-[#52525B] text-xs uppercase tracking-wider min-w-[160px] w-[160px]">
          Status
        </TableHead>
        <TableHead className="sticky top-0 z-10 bg-[#0A0A0A]/95 backdrop-blur text-[#52525B] text-xs uppercase tracking-wider min-w-[148px] w-[148px]">
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="cursor-help">Next follow-up</span>
            </TooltipTrigger>
            <TooltipContent className="bg-[#1A1A1A] border border-white/10 text-[#EDEDED]">
              Earliest of next_action_date or earliest pending task due time.
            </TooltipContent>
          </Tooltip>
        </TableHead>
        <TableHead className="sticky top-0 z-10 bg-[#0A0A0A]/95 backdrop-blur text-[#52525B] text-xs uppercase tracking-wider min-w-[100px]">
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="cursor-help">Active tasks</span>
            </TooltipTrigger>
            <TooltipContent className="bg-[#1A1A1A] border border-white/10 text-[#EDEDED]">Pending tasks linked to this lead.</TooltipContent>
          </Tooltip>
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
  );
}

function renderLeadRows(rows, handlers, density) {
  return rows.map((row) => (
    <LeadTableRow
      key={row.lead.id}
      lead={row.lead}
      taskCount={row.taskCount}
      followUp={row.followUp}
      earliestTaskId={row.earliestTaskId}
      recentNote={row.recentNote}
      tint={row.tint}
      density={density}
      onRowClick={handlers.onRowClick}
      onNote={handlers.onNote}
      onOpenLeadTasks={handlers.onOpenLeadTasks}
    />
  ));
}

export const LeadDataTable = memo(function LeadDataTable({
  leads,
  loading,
  pendingTaskMap,
  pendingTasksList = [],
  earliestTaskMap,
  onRowClick,
  onView,
  onNote,
  onOpenLeadTasks,
  density = 'comfortable',
}) {
  const tableAnchorRef = useRef(null);
  const [scrollMargin, setScrollMargin] = useState(0);

  const rows = useMemo(() => {
    return leads.map((lead) => {
      const taskCount = pendingTaskMap?.get(lead.id) || 0;
      const t = (lead.temperature || '').trim();
      const isNurtureTemp = isNurturingStatus(lead.lead_status) && (t === 'Hot' || t === 'Warm');
      return {
        lead,
        taskCount,
        followUp: formatFollowUp(lead, [], pendingTaskMap, earliestTaskMap),
        earliestTaskId: earliestTaskMap?.get(lead.id)?.id || null,
        recentNote: getRecentNote(lead),
        tint: isNurtureTemp
          ? getNurtureTemperatureTintClass(lead.lead_status, t, { includeHover: true })
          : '',
      };
    });
  }, [leads, pendingTaskMap, earliestTaskMap]);

  const useVirtualTable = shouldUseVirtualList(rows.length);

  useLayoutEffect(() => {
    if (!useVirtualTable) return undefined;
    const el = tableAnchorRef.current;
    if (!el) return undefined;
    const update = () => {
      const rect = el.getBoundingClientRect();
      setScrollMargin(rect.top + window.scrollY);
    };
    update();
    window.addEventListener('resize', update);
    return () => {
      window.removeEventListener('resize', update);
    };
  }, [useVirtualTable, rows.length]);

  const rowVirtualizer = useWindowVirtualizer({
    count: rows.length,
    estimateSize: () => getVirtualRowEstimate(density),
    overscan: 10,
    scrollMargin,
    enabled: useVirtualTable,
  });

  const virtualItems = rowVirtualizer.getVirtualItems();
  const paddingTop = virtualItems.length > 0 ? Math.max(0, virtualItems[0].start - scrollMargin) : 0;
  const paddingBottom = virtualItems.length > 0
    ? rowVirtualizer.getTotalSize() - virtualItems[virtualItems.length - 1].end
    : 0;

  const measureElementRef = useRef(null);
  measureElementRef.current = rowVirtualizer.measureElement;

  const handleRowResize = useCallback((rowEl) => {
    if (rowEl) measureElementRef.current?.(rowEl);
  }, []);

  const rowHandlers = useMemo(
    () => ({ onRowClick, onNote, onOpenLeadTasks }),
    [onRowClick, onNote, onOpenLeadTasks],
  );

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
      ref={tableAnchorRef}
      className="rounded-lg border border-white/5 bg-[#1A1A1A] overflow-x-auto"
      data-testid="lead-data-table"
    >
      {useVirtualTable ? (
        <table className={TABLE_LAYOUT_CLASS}>
          <LeadTableColGroup />
          <LeadTableHeader />
          <TableBody>
            {paddingTop > 0 && (
              <TableRow aria-hidden className="border-0 hover:bg-transparent">
                <TableCell colSpan={COLUMN_COUNT} style={{ height: paddingTop, padding: 0, border: 0 }} />
              </TableRow>
            )}
            {virtualItems.map((vi) => {
              const row = rows[vi.index];
              return (
                <LeadTableRow
                  key={row.lead.id}
                  data-index={vi.index}
                  lead={row.lead}
                  taskCount={row.taskCount}
                  followUp={row.followUp}
                  earliestTaskId={row.earliestTaskId}
                  recentNote={row.recentNote}
                  tint={row.tint}
                  onRowClick={onRowClick}
                  onNote={onNote}
                  onOpenLeadTasks={onOpenLeadTasks}
                  density={density}
                  onRowResize={handleRowResize}
                />
              );
            })}
            {paddingBottom > 0 && (
              <TableRow aria-hidden className="border-0 hover:bg-transparent">
                <TableCell colSpan={COLUMN_COUNT} style={{ height: paddingBottom, padding: 0, border: 0 }} />
              </TableRow>
            )}
          </TableBody>
        </table>
      ) : (
        <Table className={TABLE_LAYOUT_CLASS}>
          <LeadTableColGroup />
          <LeadTableHeader />
          <TableBody>
            {renderLeadRows(rows, rowHandlers, density)}
          </TableBody>
        </Table>
      )}
    </div>
  );
});

export default LeadDataTable;
