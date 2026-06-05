import { formatDateTimeIST, formatDueDateTime } from './datetime';

const GENERIC_SLA_TITLES = new Set([
  'reassign lead',
  'alert admin',
  'rnr reminder',
  'admin review required',
  'escalate to admin',
  'agent reminder + manager flag',
  'admin alert',
  'hot lead follow-up',
  'warm lead follow-up',
  'missing visit date: update required',
  'send wa reminder to client',
  'post-visit follow-up',
  'push for booking',
  'manager flag',
  'negotiation follow-up',
  're-evaluate - re-engage or close',
  '90-day check-in',
]);

export function todayYmd() {
  return new Date().toISOString().slice(0, 10);
}

/** @returns {'overdue'|'due_today'|'upcoming'|'none'} */
export function getTaskDueBucket(dueDateYmd) {
  if (!dueDateYmd) return 'none';
  const due = String(dueDateYmd).slice(0, 10);
  const today = todayYmd();
  if (due < today) return 'overdue';
  if (due === today) return 'due_today';
  return 'upcoming';
}

export function getDueStatusBadge(bucket) {
  switch (bucket) {
    case 'overdue':
      return {
        label: 'Overdue',
        className: 'bg-red-500/20 text-red-400 border border-red-500/30',
      };
    case 'due_today':
      return {
        label: 'Due Today',
        className: 'bg-orange-500/20 text-orange-400 border border-orange-500/30',
      };
    case 'upcoming':
      return {
        label: 'Upcoming',
        className: 'bg-blue-500/20 text-blue-400 border border-blue-500/30',
      };
    default:
      return {
        label: 'No Due Date',
        className: 'bg-gray-500/20 text-gray-400 border border-gray-500/30',
      };
  }
}

export function getCompletedStatusBadge() {
  return {
    label: 'Completed',
    className: 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30',
  };
}

export function getPriorityBadge(priority) {
  const p = (priority || 'medium').toLowerCase();
  if (p === 'high') {
    return { label: 'High', className: 'bg-red-500/20 text-red-400' };
  }
  if (p === 'low') {
    return { label: 'Low', className: 'bg-gray-500/20 text-gray-400' };
  }
  return { label: 'Medium', className: 'bg-amber-500/20 text-amber-400' };
}

export function getTaskCardBorderClass(bucket, variant) {
  if (variant === 'completed') {
    return 'border-emerald-500/25';
  }
  if (bucket === 'overdue') return 'border-red-500/30';
  if (bucket === 'due_today') return 'border-orange-500/30';
  return 'border-white/5';
}

function isGenericSlaTitle(desc) {
  return GENERIC_SLA_TITLES.has((desc || '').trim().toLowerCase());
}

export function getTaskDisplayTitle(task) {
  const desc = (task?.description || 'Task').trim();
  const lead = (task?.lead_name || '').trim();
  if (!lead) return desc;
  if (desc.toLowerCase().includes(lead.toLowerCase())) return desc;
  if (isGenericSlaTitle(desc)) {
    return `${lead} — ${desc}`;
  }
  return `${desc} · ${lead}`;
}

export function getTaskReason(task) {
  const reason = (task?.task_reason || task?.latest_note || '').trim();
  return reason || null;
}

export function formatTaskDue(task) {
  if (!task?.due_date) return null;
  return formatDueDateTime(task.due_date, task.due_time);
}

export function formatTaskCreated(task) {
  const raw = task?.created_at_dt || task?.created_at;
  if (!raw) return null;
  return formatDateTimeIST(raw) || String(raw);
}

export function getAssignedDisplay(task) {
  return (task?.assigned_to_name || task?.assigned_to || '').trim() || '—';
}

export function getCreatedByDisplay(task) {
  return (task?.created_by || '').trim() || '—';
}
