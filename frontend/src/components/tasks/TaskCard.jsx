import React, { memo } from 'react';
import {
  Building2,
  Calendar,
  CheckCircle,
  ExternalLink,
  Pencil,
  User,
} from 'lucide-react';
import { Button } from '../ui/button';
import { CrmBadge } from '../ui/CrmBadge';
import {
  formatTaskCreated,
  formatTaskDue,
  getAssignedDisplay,
  getCreatedByDisplay,
  getCompletedStatusBadge,
  getDueStatusBadge,
  getPriorityBadge,
  getTaskCardBorderClass,
  getTaskDisplayTitle,
  getTaskDueBucket,
  getTaskReason,
} from '../../utils/taskDisplay';

export const TaskCard = memo(function TaskCard({
  task,
  variant = 'pending',
  index = 0,
  onComplete,
  onViewLead,
  onEdit,
  onOpenDetail,
}) {
  const isCompleted = variant === 'completed';
  const dueBucket = isCompleted ? 'none' : getTaskDueBucket(task?.due_date);
  const statusBadge = isCompleted ? getCompletedStatusBadge() : getDueStatusBadge(dueBucket);
  const priorityBadge = getPriorityBadge(task?.priority);
  const title = getTaskDisplayTitle(task);
  const reason = getTaskReason(task);
  const dueLabel = formatTaskDue(task);
  const createdLabel = formatTaskCreated(task);
  const leadName = (task?.lead_name || '').trim();
  const project = (task?.project || '').trim();
  const taskId = task?.id || 'unknown';

  const stop = (e) => e.stopPropagation();

  return (
    <div
      role={onOpenDetail ? 'button' : undefined}
      tabIndex={onOpenDetail ? 0 : undefined}
      onClick={() => onOpenDetail?.(task)}
      onKeyDown={(e) => {
        if (onOpenDetail && (e.key === 'Enter' || e.key === ' ')) {
          e.preventDefault();
          onOpenDetail(task);
        }
      }}
      className={[
        'bg-crm-elevated border rounded-lg p-3 transition-colors',
        getTaskCardBorderClass(dueBucket, variant),
        onOpenDetail ? 'cursor-pointer hover:border-[#C5A059]/30' : '',
        isCompleted ? 'opacity-85' : '',
      ].join(' ')}
      data-testid={`task-card-${taskId}`}
    >
      <div className="flex items-start gap-2">
        {!isCompleted ? (
          <button
            type="button"
            onClick={(e) => {
              stop(e);
              onComplete?.(task);
            }}
            className={`w-5 h-5 rounded-full border-2 flex items-center justify-center flex-shrink-0 mt-1 transition-colors ${
              dueBucket === 'overdue'
                ? 'border-red-500 hover:bg-red-500/20'
                : 'border-[#52525B] hover:border-[#C5A059]'
            }`}
            aria-label="Mark complete"
            data-testid={`task-complete-${taskId}`}
          >
            <CheckCircle size={10} className="opacity-0 hover:opacity-100" />
          </button>
        ) : (
          <CheckCircle size={18} className="text-emerald-500 flex-shrink-0 mt-0.5" />
        )}

        <div className="flex-1 min-w-0 space-y-1.5">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <h3
              className={`font-medium text-sm leading-snug pr-2 ${
                isCompleted ? 'text-crm-fg-secondary line-through' : 'text-white'
              }`}
            >
              {title}
            </h3>
            <CrmBadge variant={statusBadge.variant} size="xs" uppercase className="flex-shrink-0">
              {statusBadge.label}
            </CrmBadge>
          </div>

          {(leadName || project) && (
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-crm-fg-secondary">
              {leadName && (
                <span className="flex items-center gap-1">
                  <User size={12} className="text-crm-fg-muted" />
                  <span className="text-crm-fg-muted">Lead:</span>
                  <span className={task?.lead_id ? 'text-[#C5A059]' : 'text-white'}>{leadName}</span>
                </span>
              )}
              {project && (
                <span className="flex items-center gap-1">
                  <Building2 size={12} className="text-crm-fg-muted" />
                  <span className="text-crm-fg-muted">Project:</span>
                  <span className="text-white">{project}</span>
                </span>
              )}
            </div>
          )}

          {reason && (
            <div className="rounded-lg bg-black/25 border border-white/5 px-3 py-2">
              <p className="text-crm-fg-muted text-[10px] uppercase tracking-wider mb-0.5">Reason</p>
              <p className="text-crm-fg text-xs leading-relaxed line-clamp-2">{reason}</p>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 text-xs">
            {dueLabel && (
              <span
                className={`flex items-center gap-1 ${
                  dueBucket === 'overdue' ? 'text-red-400' : 'text-crm-fg-secondary'
                }`}
              >
                <Calendar size={12} />
                Due: {dueLabel}
              </span>
            )}
            <CrmBadge variant={priorityBadge.variant} size="xs" uppercase>
              {priorityBadge.label}
            </CrmBadge>
            <span className="text-crm-fg-muted flex items-center gap-1">
              <User size={10} />
              {getAssignedDisplay(task)}
            </span>
          </div>

          {(createdLabel || getCreatedByDisplay(task) !== '—') && (
            <p className="text-crm-fg-muted text-[10px]">
              Created by {getCreatedByDisplay(task)}
              {createdLabel ? ` · ${createdLabel}` : ''}
            </p>
          )}

          {!isCompleted && (
            <div className="flex flex-wrap gap-2 pt-1" onClick={stop}>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-8 border-crm-border text-white hover:bg-white/5 text-xs"
                disabled={!task?.lead_id}
                onClick={() => onViewLead?.(task?.lead_id)}
                data-testid={`task-view-lead-${taskId}`}
              >
                <ExternalLink size={14} className="mr-1.5" />
                View Lead
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-8 border-crm-border text-white hover:bg-white/5 text-xs"
                onClick={() => onEdit?.(task)}
                data-testid={`task-edit-${taskId}`}
              >
                <Pencil size={14} className="mr-1.5" />
                Edit
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
});

export default TaskCard;
