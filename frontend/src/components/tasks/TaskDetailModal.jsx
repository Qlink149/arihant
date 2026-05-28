import React, { useMemo } from 'react';
import { Calendar, ExternalLink, Flag } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/dialog';
import { Button } from '../ui/button';
import { formatDueDateTime } from '../../utils/datetime';

const isOverdueYmd = (ymd) => {
  if (!ymd) return false;
  const today = new Date().toISOString().slice(0, 10);
  return String(ymd) < today;
};

export function TaskDetailModal({
  open,
  onOpenChange,
  task,
  onComplete,
  onOpenLead,
}) {
  const overdue = isOverdueYmd(task?.due_date);
  const due = task?.due_date ? formatDueDateTime(task.due_date, task.due_time) : null;
  const isSla = useMemo(() => (task?.source || '').toLowerCase() === 'sla', [task?.source]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#1A1A1A] border-white/10 text-white max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-serif text-xl flex items-center gap-2">
            {isSla ? <Flag size={18} className="text-[#C5A059]" /> : null}
            Task details
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div className="rounded-lg border border-white/10 bg-black/20 p-3">
            <p className="text-white text-sm break-words">{task?.description || '—'}</p>

            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-[#A1A1AA]">
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
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[#C5A059]/10 text-[#C5A059] border border-[#C5A059]/20">
                  {String(task?.sla_rule || 'sla').toUpperCase()}
                  {task?.sla_threshold ? ` · ${task.sla_threshold}` : ''}
                </span>
              ) : null}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="rounded-lg border border-white/10 bg-black/20 p-3">
              <p className="text-[#52525B] text-xs uppercase tracking-wider">Assigned to</p>
              <p className="text-white text-sm mt-1">{task?.assigned_to_name || task?.assigned_to || '—'}</p>
            </div>
            <div className="rounded-lg border border-white/10 bg-black/20 p-3">
              <p className="text-[#52525B] text-xs uppercase tracking-wider">Status</p>
              <p className="text-white text-sm mt-1">{task?.status || '—'}</p>
            </div>
          </div>

          {task?.lead_id ? (
            <div className="rounded-lg border border-white/10 bg-black/20 p-3 flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[#52525B] text-xs uppercase tracking-wider">Linked lead</p>
                <p className="text-white text-sm mt-1 truncate">
                  {task?.lead_name || task?.lead_id}
                </p>
              </div>
              <Button
                type="button"
                variant="outline"
                className="border-white/10 text-white hover:bg-white/5"
                onClick={() => onOpenLead?.(task.lead_id)}
              >
                <ExternalLink size={14} className="mr-2" />
                Open lead
              </Button>
            </div>
          ) : null}

          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              className="border-white/10 text-white hover:bg-white/5"
              onClick={() => onOpenChange?.(false)}
            >
              Close
            </Button>
            {task?.status === 'pending' ? (
              <Button
                type="button"
                className="bg-[#C5A059] text-black hover:bg-[#E5C079]"
                onClick={() => onComplete?.(task)}
              >
                Mark complete
              </Button>
            ) : null}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default TaskDetailModal;

