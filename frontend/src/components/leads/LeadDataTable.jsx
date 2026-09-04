import React, { memo, useMemo, useState, useRef, useLayoutEffect, useCallback, useEffect } from 'react';
import { useWindowVirtualizer } from '@tanstack/react-virtual';
import { Crown, ListChecks, UserPlus, CircleDot, X } from 'lucide-react';
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
import { formatDateTimeIST, formatDateIST } from '../../utils/datetime';
import { formatLeadProjects } from '../../utils/leadProjects';
import { CrmBadge } from '../ui/CrmBadge';
import { Tooltip, TooltipContent, TooltipTrigger } from '../ui/tooltip';
import {
  shouldUseVirtualList,
  getVirtualRowEstimate,
} from '../../constants/performanceFlags';
import { Checkbox } from '../ui/checkbox';
import { Button } from '../ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '../ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../ui/select';
import { Input } from '../ui/input';
import { leadsAPI } from '../../services/api';
import { UI_LEAD_STATUSES as LEAD_STATUSES } from '../../constants/leadStatus';
import {
  LOST_REASON_OPTIONS,
  isLostReasonEnumStatus,
  isLostReasonStatus,
  isCanonicalLostReason,
} from '../../constants/lostReason';
import { toast } from 'sonner';

const BASE_COLUMN_COUNT = 12;
const CHECKBOX_COL_WIDTH = 44;

// Name, Phone, Status, Follow-up, Tasks, Project, Source, Recent note, Sales owner, Created, Updated, Actions
const LEAD_TABLE_COLUMNS = [200, 130, 160, 148, 100, 160, 120, 280, 140, 148, 148, 88];

function LeadTableColGroup({ showCheckbox }) {
  return (
    <colgroup>
      {showCheckbox && <col style={{ width: CHECKBOX_COL_WIDTH }} />}
      {LEAD_TABLE_COLUMNS.map((width, index) => (
        <col key={index} style={{ width }} />
      ))}
    </colgroup>
  );
}

const TABLE_LAYOUT_CLASS = 'table-fixed min-w-[1822px] w-full caption-bottom text-sm';

function formatLeadStamp(lead, keys) {
  for (const key of keys) {
    const raw = lead?.[key];
    const formatted = formatDateTimeIST(raw);
    if (formatted) return formatted;
  }
  return '—';
}

function formatLeadCreatedAt(lead) {
  return formatLeadStamp(lead, ['created_at', 'created_at_dt']);
}

function formatLeadUpdatedAt(lead) {
  return formatLeadStamp(lead, ['updated_at', 'updated_at_dt']);
}

const RecentNoteCell = memo(function RecentNoteCell({ note, leadId, onResize }) {
  const [expanded, setExpanded] = useState(false);

  const normalized = useMemo(() => String(note || '').trim(), [note]);
  const isExpandable = useMemo(() => {
    if (!normalized) return false;
    return normalized.length > 140 || normalized.includes('\n');
  }, [normalized]);

  if (!normalized) {
    return <span className="text-crm-fg-muted text-sm">—</span>;
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
          'text-crm-fg-secondary text-sm break-words',
          expanded
            ? 'whitespace-pre-wrap max-h-80 overflow-y-auto rounded-md border border-crm-border bg-black/20 p-2'
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
          className="mt-1 text-[11px] text-crm-fg-muted hover:text-[#C5A059] underline-offset-2 hover:underline"
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
  onNudge,
  canNudge,
  onOpenLeadTasks,
  onRowResize,
  density = 'comfortable',
  showCheckbox = false,
  selected = false,
  onToggleSelect,
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
      className={`border-white/5 cursor-pointer ${tint || 'hover:bg-white/5'} ${selected ? 'bg-[#C5A059]/5' : ''}`}
      onClick={() => onRowClick(lead.id)}
      data-testid={`lead-row-${lead.id}`}
      data-lead-row-id={lead.id}
    >
      {showCheckbox && (
        <TableCell className={`${cellPy} w-[44px]`} onClick={(e) => e.stopPropagation()}>
          <Checkbox
            checked={selected}
            onCheckedChange={() => onToggleSelect?.(lead.id)}
            onClick={(e) => e.stopPropagation()}
            aria-label={`Select ${fullName || 'lead'}`}
            data-testid={`lead-select-${lead.id}`}
            className="border-crm-border data-[state=checked]:bg-[#C5A059] data-[state=checked]:border-[#C5A059]"
          />
        </TableCell>
      )}
      <TableCell className={`${cellPy} w-[200px] max-w-[200px] overflow-hidden`}>
        <div className={`flex items-center ${density === 'compact' ? 'gap-2' : 'gap-3'} min-w-0 w-full overflow-hidden`}>
          <div className="flex-shrink-0">
            <LeadAvatar lead={lead} size={avatarSize} />
          </div>
          <div className="min-w-0 flex-1 overflow-hidden">
            <div className="flex items-center gap-1.5 min-w-0 overflow-hidden">
              <span
                className={`text-crm-fg font-medium ${textSize} truncate`}
                title={fullName || undefined}
              >
                {lead.first_name} {lead.last_name}
              </span>
              {lead.vip && (
                <Crown className="text-purple-500 flex-shrink-0" size={14} aria-label="VIP" />
              )}
              {lead.re_enquiry && (
                <CrmBadge
                  variant="info"
                  size="xs"
                  title={lead.re_enquired_at ? `Last re-enquiry ${formatDateIST(lead.re_enquired_at)}` : 'Re Enquiry'}
                  data-testid={`re-enquiry-badge-${lead.id}`}
                >
                  Re Enquiry
                </CrmBadge>
              )}
              {lead.whatsapp_replied && (
                <CrmBadge
                  variant="success"
                  size="xs"
                  title="Replied on WhatsApp"
                  data-testid={`wa-replied-badge-${lead.id}`}
                >
                  WA
                </CrmBadge>
              )}
            </div>
          </div>
        </div>
      </TableCell>
      <TableCell className={`${cellPy} w-[130px] max-w-[130px] min-w-0 overflow-hidden`}>
        <span
          className={`text-crm-fg font-semibold ${textSize} truncate block`}
          title={lead.phone || undefined}
          data-testid={`lead-phone-${lead.id}`}
        >
          {lead.phone || '—'}
        </span>
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
            className={`text-crm-fg ${textSize} font-medium hover:text-[#C5A059] underline-offset-2 hover:underline truncate block max-w-full text-left`}
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
          <span className={`text-crm-fg-muted ${textSize}`}>—</span>
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
          <span className={`text-crm-fg-muted ${textSize}`}>—</span>
        )}
      </TableCell>
      <TableCell className={`${cellPy} max-w-[200px]`}>
        <span
          className={`text-crm-fg font-semibold ${textSize} truncate block`}
          title={formatLeadProjects(lead, '')}
          data-testid={`lead-project-${lead.id}`}
        >
          {formatLeadProjects(lead)}
        </span>
      </TableCell>
      <TableCell className={`${cellPy} max-w-[140px]`}>
        <span className={`text-crm-fg-muted ${textSize} truncate block`} title={lead.lead_source || ''}>
          {lead.lead_source || '—'}
        </span>
      </TableCell>
      <TableCell className={`${cellPy} overflow-hidden`}>
        <RecentNoteCell note={recentNote} leadId={lead.id} onResize={handleNoteResize} />
      </TableCell>
      <TableCell className={cellPy}>
        <div className="flex items-center gap-2 min-w-0">
          {owner !== '—' && (
            <LeadAvatar lead={{ first_name: owner, last_name: '', id: owner }} size="sm" />
          )}
          <span className={`text-crm-fg-secondary ${textSize} truncate`} title={owner}>
            {owner}
          </span>
        </div>
      </TableCell>
      <TableCell className={`${cellPy} max-w-[148px]`}>
        <span
          className={`text-crm-fg-secondary ${textSize} truncate block`}
          title={formatLeadCreatedAt(lead)}
          data-testid={`lead-created-${lead.id}`}
        >
          {formatLeadCreatedAt(lead)}
        </span>
      </TableCell>
      <TableCell className={`${cellPy} max-w-[148px]`}>
        <span
          className={`text-crm-fg-secondary ${textSize} truncate block`}
          title={formatLeadUpdatedAt(lead)}
          data-testid={`lead-updated-${lead.id}`}
        >
          {formatLeadUpdatedAt(lead)}
        </span>
      </TableCell>
      <TableCell className={cellPy}>
        <LeadRowActions
          leadId={lead.id}
          onNote={onNote}
          onNudge={onNudge}
          canNudge={canNudge}
          nudgeDisabled={
            !(lead.assigned_user_id || lead.assigned_to_name || lead.assigned_to || lead.presales_agent)
          }
        />
      </TableCell>
    </TableRow>
  );
});

function LeadTableHeader({
  showCheckbox = false,
  allSelected = false,
  someSelected = false,
  onToggleSelectAll,
}) {
  return (
    <TableHeader>
      <TableRow className="border-crm-border hover:bg-transparent">
        {showCheckbox && (
          <TableHead className="sticky top-0 z-10 bg-crm backdrop-blur w-[44px] px-2">
            <Checkbox
              checked={allSelected ? true : someSelected ? 'indeterminate' : false}
              onCheckedChange={() => onToggleSelectAll?.()}
              onClick={(e) => e.stopPropagation()}
              aria-label="Select all loaded leads"
              data-testid="lead-select-all"
              className="border-crm-border data-[state=checked]:bg-[#C5A059] data-[state=checked]:border-[#C5A059]"
            />
          </TableHead>
        )}
        <TableHead className="sticky top-0 z-10 bg-crm backdrop-blur text-crm-fg-muted text-xs uppercase tracking-wider min-w-[200px]">
          Name
        </TableHead>
        <TableHead className="sticky top-0 z-10 bg-crm backdrop-blur text-crm-fg-muted text-xs uppercase tracking-wider min-w-[130px] w-[130px]">
          Phone
        </TableHead>
        <TableHead className="sticky top-0 z-10 bg-crm backdrop-blur text-crm-fg-muted text-xs uppercase tracking-wider min-w-[160px]">
          Status
        </TableHead>
        <TableHead className="sticky top-0 z-10 bg-crm backdrop-blur text-crm-fg-muted text-xs uppercase tracking-wider min-w-[148px]">
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="cursor-help">Next follow-up</span>
            </TooltipTrigger>
            <TooltipContent className="bg-crm-elevated border border-crm-border text-crm-fg">
              Earliest of next_action_date or earliest pending task due time.
            </TooltipContent>
          </Tooltip>
        </TableHead>
        <TableHead className="sticky top-0 z-10 bg-crm backdrop-blur text-crm-fg-muted text-xs uppercase tracking-wider min-w-[100px]">
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="cursor-help">Active tasks</span>
            </TooltipTrigger>
            <TooltipContent className="bg-crm-elevated border border-crm-border text-crm-fg">Pending tasks linked to this lead.</TooltipContent>
          </Tooltip>
        </TableHead>
        <TableHead className="sticky top-0 z-10 bg-crm backdrop-blur text-crm-fg-muted text-xs uppercase tracking-wider min-w-[160px]">
          Project
        </TableHead>
        <TableHead className="sticky top-0 z-10 bg-crm backdrop-blur text-crm-fg-muted text-xs uppercase tracking-wider min-w-[120px]">
          Source
        </TableHead>
        <TableHead className="sticky top-0 z-10 bg-crm backdrop-blur text-crm-fg-muted text-xs uppercase tracking-wider min-w-[220px] max-w-[320px]">
          Recent note
        </TableHead>
        <TableHead className="sticky top-0 z-10 bg-crm backdrop-blur text-crm-fg-muted text-xs uppercase tracking-wider min-w-[140px]">
          Sales owner
        </TableHead>
        <TableHead className="sticky top-0 z-10 bg-crm backdrop-blur text-crm-fg-muted text-xs uppercase tracking-wider min-w-[148px] w-[148px]">
          Created
        </TableHead>
        <TableHead className="sticky top-0 z-10 bg-crm backdrop-blur text-crm-fg-muted text-xs uppercase tracking-wider min-w-[148px] w-[148px]">
          Updated
        </TableHead>
        <TableHead className="sticky top-0 z-10 bg-crm backdrop-blur text-crm-fg-muted text-xs uppercase tracking-wider w-[88px] text-right">
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
      onNudge={handlers.onNudge}
      canNudge={handlers.canNudge}
      onOpenLeadTasks={handlers.onOpenLeadTasks}
      showCheckbox={handlers.showCheckbox}
      selected={handlers.selectedIds?.has(row.lead.id)}
      onToggleSelect={handlers.onToggleSelect}
    />
  ));
}

function needsLostReason(status) {
  const s = (status || '').trim().toLowerCase();
  return isLostReasonStatus(status) || s === 'junk' || s === 'dropped';
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
  onNudge,
  canNudge = false,
  onOpenLeadTasks,
  density = 'comfortable',
  bulkSelectEnabled = false,
  assigneeOptions = [],
  onBulkComplete,
}) {
  const tableAnchorRef = useRef(null);
  const [scrollMargin, setScrollMargin] = useState(0);
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [assignOpen, setAssignOpen] = useState(false);
  const [statusOpen, setStatusOpen] = useState(false);
  const [pendingAssigneeId, setPendingAssigneeId] = useState('');
  const [pendingStatus, setPendingStatus] = useState('');
  const [pendingLostReason, setPendingLostReason] = useState('');
  const [submitting, setSubmitting] = useState(false);

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

  const loadedIds = useMemo(() => leads.map((l) => l.id), [leads]);
  const columnCount = bulkSelectEnabled ? BASE_COLUMN_COUNT + 1 : BASE_COLUMN_COUNT;

  useEffect(() => {
    if (!bulkSelectEnabled) {
      setSelectedIds(new Set());
      return;
    }
    const loaded = new Set(loadedIds);
    setSelectedIds((prev) => {
      let changed = false;
      const next = new Set();
      prev.forEach((id) => {
        if (loaded.has(id)) next.add(id);
        else changed = true;
      });
      return changed || next.size !== prev.size ? next : prev;
    });
  }, [bulkSelectEnabled, loadedIds]);

  const allSelected = bulkSelectEnabled && loadedIds.length > 0 && loadedIds.every((id) => selectedIds.has(id));
  const someSelected = bulkSelectEnabled && !allSelected && loadedIds.some((id) => selectedIds.has(id));
  const selectedCount = selectedIds.size;

  const toggleSelect = useCallback((leadId) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(leadId)) next.delete(leadId);
      else next.add(leadId);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    setSelectedIds((prev) => {
      const allOn = loadedIds.length > 0 && loadedIds.every((id) => prev.has(id));
      if (allOn) return new Set();
      return new Set(loadedIds);
    });
  }, [loadedIds]);

  const clearSelection = useCallback(() => setSelectedIds(new Set()), []);

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
    () => ({
      onRowClick,
      onNote,
      onNudge,
      canNudge,
      onOpenLeadTasks,
      showCheckbox: bulkSelectEnabled,
      selectedIds,
      onToggleSelect: toggleSelect,
    }),
    [onRowClick, onNote, onNudge, canNudge, onOpenLeadTasks, bulkSelectEnabled, selectedIds, toggleSelect],
  );

  const reportBulkResult = useCallback((data) => {
    const updated = data?.updated || [];
    const failed = data?.failed || [];
    if (updated.length && !failed.length) {
      toast.success(`Updated ${updated.length} lead${updated.length === 1 ? '' : 's'}`);
    } else if (updated.length && failed.length) {
      toast.message(`Updated ${updated.length}, ${failed.length} failed`);
    } else if (failed.length) {
      toast.error(failed[0]?.reason || 'Bulk update failed');
    }
  }, []);

  const handleBulkAssign = useCallback(async () => {
    const assignee = assigneeOptions.find((a) => String(a.id) === String(pendingAssigneeId));
    if (!assignee) {
      toast.error('Select an assignee');
      return;
    }
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    setSubmitting(true);
    try {
      const res = await leadsAPI.bulkUpdate({
        lead_ids: ids,
        assigned_user_id: assignee.id,
        to_rep: assignee.full_name,
      });
      reportBulkResult(res?.data);
      setAssignOpen(false);
      setPendingAssigneeId('');
      clearSelection();
      await onBulkComplete?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Bulk assign failed');
    } finally {
      setSubmitting(false);
    }
  }, [assigneeOptions, pendingAssigneeId, selectedIds, reportBulkResult, clearSelection, onBulkComplete]);

  const handleBulkStatus = useCallback(async () => {
    if (!pendingStatus) {
      toast.error('Select a status');
      return;
    }
    if (needsLostReason(pendingStatus)) {
      const reason = (pendingLostReason || '').trim();
      if (!reason) {
        toast.error('Lost reason is required for this status');
        return;
      }
      if (isLostReasonEnumStatus(pendingStatus) && !isCanonicalLostReason(reason)) {
        toast.error('Select a valid lost reason');
        return;
      }
    }
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    setSubmitting(true);
    try {
      const payload = {
        lead_ids: ids,
        lead_status: pendingStatus,
      };
      if (needsLostReason(pendingStatus)) {
        payload.lost_reason = pendingLostReason.trim();
      }
      const res = await leadsAPI.bulkUpdate(payload);
      reportBulkResult(res?.data);
      setStatusOpen(false);
      setPendingStatus('');
      setPendingLostReason('');
      clearSelection();
      await onBulkComplete?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Bulk status update failed');
    } finally {
      setSubmitting(false);
    }
  }, [pendingStatus, pendingLostReason, selectedIds, reportBulkResult, clearSelection, onBulkComplete]);

  if (loading) {
    return (
      <div className="rounded-lg border border-white/5 bg-crm-elevated overflow-hidden">
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
      <div className="rounded-lg border border-white/5 bg-crm-elevated p-12 text-center">
        <p className="text-crm-fg-secondary">No leads found</p>
        <p className="text-crm-fg-muted text-sm mt-1">Try adjusting your filters</p>
      </div>
    );
  }

  const showLostField = needsLostReason(pendingStatus);
  const showLostEnum = isLostReasonEnumStatus(pendingStatus);

  return (
    <>
      <div
        ref={tableAnchorRef}
        className="rounded-lg border border-white/5 bg-crm-elevated overflow-x-auto"
        data-testid="lead-data-table"
      >
        {useVirtualTable ? (
          <table className={TABLE_LAYOUT_CLASS}>
            <LeadTableColGroup showCheckbox={bulkSelectEnabled} />
            <LeadTableHeader
              showCheckbox={bulkSelectEnabled}
              allSelected={allSelected}
              someSelected={someSelected}
              onToggleSelectAll={toggleSelectAll}
            />
            <TableBody>
              {paddingTop > 0 && (
                <TableRow aria-hidden className="border-0 hover:bg-transparent">
                  <TableCell colSpan={columnCount} style={{ height: paddingTop, padding: 0, border: 0 }} />
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
                    onNudge={onNudge}
                    canNudge={canNudge}
                    onOpenLeadTasks={onOpenLeadTasks}
                    density={density}
                    onRowResize={handleRowResize}
                    showCheckbox={bulkSelectEnabled}
                    selected={selectedIds.has(row.lead.id)}
                    onToggleSelect={toggleSelect}
                  />
                );
              })}
              {paddingBottom > 0 && (
                <TableRow aria-hidden className="border-0 hover:bg-transparent">
                  <TableCell colSpan={columnCount} style={{ height: paddingBottom, padding: 0, border: 0 }} />
                </TableRow>
              )}
            </TableBody>
          </table>
        ) : (
          <Table className={TABLE_LAYOUT_CLASS}>
            <LeadTableColGroup showCheckbox={bulkSelectEnabled} />
            <LeadTableHeader
              showCheckbox={bulkSelectEnabled}
              allSelected={allSelected}
              someSelected={someSelected}
              onToggleSelectAll={toggleSelectAll}
            />
            <TableBody>
              {renderLeadRows(rows, rowHandlers, density)}
            </TableBody>
          </Table>
        )}
      </div>

      {bulkSelectEnabled && selectedCount > 0 && (
        <div
          className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 flex items-center gap-3 px-4 py-3 rounded-xl border border-crm-border bg-crm-elevated shadow-lg"
          data-testid="lead-bulk-bar"
        >
          <span className="text-sm text-crm-fg whitespace-nowrap">
            {selectedCount} selected
          </span>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 border-crm-border text-crm-fg-secondary hover:text-crm-fg gap-1.5"
            onClick={() => {
              setPendingAssigneeId('');
              setAssignOpen(true);
            }}
            data-testid="bulk-assign-btn"
          >
            <UserPlus size={14} />
            Assign
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-8 border-crm-border text-crm-fg-secondary hover:text-crm-fg gap-1.5"
            onClick={() => {
              setPendingStatus('');
              setPendingLostReason('');
              setStatusOpen(true);
            }}
            data-testid="bulk-status-btn"
          >
            <CircleDot size={14} />
            Change Status
          </Button>
          <button
            type="button"
            onClick={clearSelection}
            className="ml-1 p-1.5 rounded-md text-crm-fg-muted hover:text-crm-fg hover:bg-white/10"
            aria-label="Clear selection"
            data-testid="bulk-clear-btn"
          >
            <X size={16} />
          </button>
        </div>
      )}

      <Dialog open={assignOpen} onOpenChange={(open) => !submitting && setAssignOpen(open)}>
        <DialogContent className="bg-crm-elevated border-crm-border text-crm-fg max-w-md" data-testid="bulk-assign-modal">
          <DialogHeader>
            <DialogTitle className="font-serif text-xl">Assign {selectedCount} leads</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 mt-2">
            <Select value={pendingAssigneeId || undefined} onValueChange={setPendingAssigneeId}>
              <SelectTrigger className="bg-crm-muted border-crm-border text-crm-fg" data-testid="bulk-assign-select">
                <SelectValue placeholder="Select assignee" />
              </SelectTrigger>
              <SelectContent className="bg-crm-elevated border-crm-border text-crm-fg max-h-64">
                {assigneeOptions.map((user) => (
                  <SelectItem key={user.id} value={String(user.id)} className="text-crm-fg hover:bg-[#C5A059]/10">
                    {user.full_name}
                    {user.role ? ` (${user.role})` : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="flex justify-end gap-2">
              <Button
                variant="ghost"
                onClick={() => setAssignOpen(false)}
                disabled={submitting}
                className="text-crm-fg-secondary"
              >
                Cancel
              </Button>
              <Button
                onClick={handleBulkAssign}
                disabled={submitting || !pendingAssigneeId}
                className="bg-[#C5A059] text-black hover:bg-[#C5A059]/90"
                data-testid="bulk-assign-confirm"
              >
                {submitting ? 'Assigning…' : 'Assign'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={statusOpen} onOpenChange={(open) => !submitting && setStatusOpen(open)}>
        <DialogContent className="bg-crm-elevated border-crm-border text-crm-fg max-w-md" data-testid="bulk-status-modal">
          <DialogHeader>
            <DialogTitle className="font-serif text-xl">Change status ({selectedCount})</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 mt-2">
            <Select
              value={pendingStatus || undefined}
              onValueChange={(value) => {
                setPendingStatus(value);
                setPendingLostReason('');
              }}
            >
              <SelectTrigger className="bg-crm-muted border-crm-border text-crm-fg" data-testid="bulk-status-select">
                <SelectValue placeholder="Select status" />
              </SelectTrigger>
              <SelectContent className="bg-crm-elevated border-crm-border text-crm-fg max-h-64">
                {LEAD_STATUSES.map((status) => (
                  <SelectItem key={status} value={status} className="text-crm-fg hover:bg-[#C5A059]/10">
                    {status}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            {showLostField && (
              <div className="space-y-2">
                <label className="text-crm-fg-muted text-xs uppercase tracking-wider">
                  {showLostEnum ? 'Lost reason (required)' : 'Reason (required)'}
                </label>
                {showLostEnum ? (
                  <Select value={pendingLostReason || undefined} onValueChange={setPendingLostReason}>
                    <SelectTrigger className="bg-crm-muted border-crm-border text-crm-fg" data-testid="bulk-lost-reason-select">
                      <SelectValue placeholder="Select lost reason" />
                    </SelectTrigger>
                    <SelectContent className="bg-crm-elevated border-crm-border text-crm-fg max-h-64">
                      {LOST_REASON_OPTIONS.map((reason) => (
                        <SelectItem key={reason} value={reason} className="text-crm-fg hover:bg-[#C5A059]/10">
                          {reason}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input
                    value={pendingLostReason}
                    onChange={(e) => setPendingLostReason(e.target.value)}
                    placeholder="Enter reason"
                    className="bg-crm-muted border-crm-border text-crm-fg"
                    data-testid="bulk-lost-reason-input"
                  />
                )}
              </div>
            )}

            <div className="flex justify-end gap-2">
              <Button
                variant="ghost"
                onClick={() => setStatusOpen(false)}
                disabled={submitting}
                className="text-crm-fg-secondary"
              >
                Cancel
              </Button>
              <Button
                onClick={handleBulkStatus}
                disabled={
                  submitting
                  || !pendingStatus
                  || (showLostField && !pendingLostReason.trim())
                  || (showLostEnum && !isCanonicalLostReason(pendingLostReason))
                }
                className="bg-[#C5A059] text-black hover:bg-[#C5A059]/90"
                data-testid="bulk-status-confirm"
              >
                {submitting ? 'Updating…' : 'Update status'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
});

export default LeadDataTable;
