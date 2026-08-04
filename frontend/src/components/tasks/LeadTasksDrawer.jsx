import React, { useMemo } from 'react';
import { Calendar, ExternalLink, Flag, ListChecks } from 'lucide-react';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '../ui/sheet';
import { Button } from '../ui/button';
import { CrmBadge } from '../ui/CrmBadge';
import {
  formatTaskDue,
  getAssignedDisplay,
  getDueStatusBadge,
  getPriorityBadge,
  getTaskCardBorderClass,
  getTaskDisplayTitle,
  getTaskDueBucket,
  getTaskReason,
} from '../../utils/taskDisplay';

function TaskRow({
  task,
  leadId,
  isHighlighted,
  onComplete,
  onOpenLead,
}) {
  const dueBucket = getTaskDueBucket(task?.due_date);
  const due = formatTaskDue(task);
  const statusBadge = getDueStatusBadge(dueBucket);
  const priorityBadge = getPriorityBadge(task?.priority);
  const reason = getTaskReason(task);
  const isSla = (task?.source || '').toLowerCase() === 'sla';

  return (
    <div
      className={[
        'lead-task-row rounded-lg border p-3 transition-colors bg-white/5',
        getTaskCardBorderClass(dueBucket, 'pending'),
        isHighlighted ? 'ring-2 ring-[#C5A059]/40' : '',
      ].join(' ')}
      data-testid={`lead-task-${task?.id || 'unknown'}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <p className="text-white text-sm break-words font-medium lead-task-title">
              {getTaskDisplayTitle(task)}
            </p>
            <CrmBadge variant={statusBadge.variant} size="xs" uppercase className="flex-shrink-0">
              {statusBadge.label}
            </CrmBadge>
          </div>

          {reason && (
            <p className="text-crm-fg-secondary text-xs line-clamp-2">{reason}</p>
          )}

          <div className="flex flex-wrap items-center gap-2 text-xs text-crm-fg-secondary">
            {due ? (
              <span className={dueBucket === 'overdue' ? 'text-red-400' : 'text-crm-fg-secondary'}>
                <Calendar size={12} className="inline mr-1" />
                Due: {due}
              </span>
            ) : (
              <span className="text-crm-fg-muted">No due date</span>
            )}

            <span className="text-crm-fg-secondary">
              Assigned to: {getAssignedDisplay(task)}
            </span>

            <CrmBadge variant={priorityBadge.variant} size="xs" uppercase>
              {priorityBadge.label}
            </CrmBadge>
            {isSla && (
              <CrmBadge variant="gold" size="xs" className="inline-flex items-center gap-1">
                <Flag size={10} />
                SLA
              </CrmBadge>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="border-crm-border text-white hover:bg-white/5 h-8"
            onClick={() => onOpenLead?.(leadId)}
          >
            <ExternalLink size={14} className="mr-1.5" />
            Lead
          </Button>
          <Button
            type="button"
            size="sm"
            className="bg-[#C5A059] text-black hover:bg-[#E5C079] h-8"
            onClick={() => onComplete?.(task)}
          >
            Done
          </Button>
        </div>
      </div>
    </div>
  );
}

export function LeadTasksDrawer({
  open,
  onOpenChange,
  lead,
  tasks,
  loading,
  highlightedTaskId,
  onCompleteTask,
  onOpenLead,
}) {
  const title = useMemo(() => {
    const name = [lead?.first_name, lead?.last_name].filter(Boolean).join(' ').trim();
    return name ? `${name} — Tasks` : 'Lead — Tasks';
  }, [lead?.first_name, lead?.last_name]);

  const subtitle = useMemo(() => {
    const count = Array.isArray(tasks) ? tasks.length : 0;
    if (loading) return 'Loading pending tasks…';
    return `${count} pending task${count === 1 ? '' : 's'}`;
  }, [tasks, loading]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="lead-tasks-drawer bg-crm-elevated border-crm-border text-white w-[min(96vw,520px)] sm:max-w-[520px]"
      >
        <SheetHeader className="pr-6">
          <SheetTitle className="font-serif text-xl text-white flex items-center gap-2">
            <ListChecks size={18} className="text-[#C5A059]" />
            {title}
          </SheetTitle>
          <p className="text-crm-fg-secondary text-sm mt-1">{subtitle}</p>
        </SheetHeader>

        <div className="mt-4 space-y-2 overflow-y-auto max-h-[calc(100vh-10rem)] pr-1">
          {loading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="h-20 rounded-lg bg-white/5 animate-pulse border border-crm-border"
                />
              ))}
            </div>
          ) : !tasks?.length ? (
            <div className="lead-task-row rounded-lg border border-crm-border bg-white/5 p-6 text-center">
              <p className="text-crm-fg-secondary text-sm">No pending tasks for this lead.</p>
              <p className="text-crm-fg-muted text-xs mt-1">
                “Active tasks” counts only tasks linked to this lead.
              </p>
            </div>
          ) : (
            tasks.map((task) => (
              <TaskRow
                key={task.id}
                task={task}
                leadId={lead?.id}
                isHighlighted={highlightedTaskId && task.id === highlightedTaskId}
                onComplete={onCompleteTask}
                onOpenLead={onOpenLead}
              />
            ))
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

export default LeadTasksDrawer;

