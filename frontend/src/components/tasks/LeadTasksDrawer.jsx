import React, { useMemo } from 'react';
import { Calendar, ExternalLink, Flag, ListChecks } from 'lucide-react';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '../ui/sheet';
import { Button } from '../ui/button';
import { formatDueDateTime } from '../../utils/datetime';

const isOverdueYmd = (ymd) => {
  if (!ymd) return false;
  const today = new Date().toISOString().slice(0, 10);
  return String(ymd) < today;
};

function TaskRow({
  task,
  leadId,
  isHighlighted,
  onComplete,
  onOpenLead,
}) {
  const overdue = isOverdueYmd(task?.due_date);
  const due = task?.due_date ? formatDueDateTime(task.due_date, task.due_time) : null;
  const isSla = (task?.source || '').toLowerCase() === 'sla';

  return (
    <div
      className={[
        'rounded-lg border p-3 transition-colors',
        overdue ? 'border-red-500/30 bg-red-500/5' : 'border-white/10 bg-black/20',
        isHighlighted ? 'ring-2 ring-[#C5A059]/40' : '',
      ].join(' ')}
      data-testid={`lead-task-${task?.id || 'unknown'}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="text-white text-sm break-words">
              {task?.description || '—'}
            </p>
            {isSla && (
              <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full bg-[#C5A059]/10 text-[#C5A059] border border-[#C5A059]/20 flex-shrink-0">
                <Flag size={10} />
                SLA
              </span>
            )}
          </div>

          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-[#A1A1AA]">
            {due ? (
              <span className={overdue ? 'text-red-400' : 'text-[#A1A1AA]'}>
                <Calendar size={12} className="inline mr-1" />
                {due}
                {overdue ? ' · Overdue' : ''}
              </span>
            ) : (
              <span className="text-[#52525B]">No due date</span>
            )}
            {task?.priority ? (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full uppercase tracking-wider bg-white/5 border border-white/10">
                {task.priority}
              </span>
            ) : null}
            {isSla && (task?.sla_rule || task?.sla_threshold) ? (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-white/5 border border-white/10">
                {String(task?.sla_rule || 'sla').toUpperCase()}
                {task?.sla_threshold ? ` · ${task.sla_threshold}` : ''}
              </span>
            ) : null}
          </div>
        </div>

        <div className="flex items-center gap-2 flex-shrink-0">
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="border-white/10 text-white hover:bg-white/5 h-8"
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
        className="bg-[#0B0B0B] border-white/10 text-white w-[min(96vw,520px)] sm:max-w-[520px]"
      >
        <SheetHeader className="pr-6">
          <SheetTitle className="font-serif text-xl text-white flex items-center gap-2">
            <ListChecks size={18} className="text-[#C5A059]" />
            {title}
          </SheetTitle>
          <p className="text-[#A1A1AA] text-sm mt-1">{subtitle}</p>
        </SheetHeader>

        <div className="mt-4 space-y-2 overflow-y-auto max-h-[calc(100vh-10rem)] pr-1">
          {loading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="h-20 rounded-lg bg-white/5 animate-pulse border border-white/10"
                />
              ))}
            </div>
          ) : !tasks?.length ? (
            <div className="rounded-lg border border-white/10 bg-black/20 p-6 text-center">
              <p className="text-[#A1A1AA] text-sm">No pending tasks for this lead.</p>
              <p className="text-[#52525B] text-xs mt-1">
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

