/** Helpers for lead list / table views */

import { dedupeContextUpdates } from './contextUpdates';
import { formatDateTimeIST, formatDueDateTime } from './datetime';

export const STATUS_COLORS = {
  New: 'bg-amber-400/25 text-amber-300 ring-1 ring-amber-400/60 font-semibold',
  Open: 'bg-blue-500/20 text-blue-400',
  Contacted: 'bg-sky-500/20 text-sky-400',
  'Follow Up': 'bg-amber-500/20 text-amber-400',
  'Follow Up 1': 'bg-amber-500/20 text-amber-400',
  'Follow Up 2': 'bg-amber-600/20 text-amber-500',
  Interested: 'bg-cyan-500/20 text-cyan-400',
  'Site Visit': 'bg-purple-500/20 text-purple-400',
  'Site Visit Scheduled': 'bg-purple-500/20 text-purple-400',
  'Site Visit Completed': 'bg-green-500/20 text-green-400',
  'Advance Paid': 'bg-emerald-500/20 text-emerald-400',
  RNR: 'bg-red-500/20 text-red-400',
  Nurturing: 'bg-orange-500/20 text-orange-400',
  'Gone Cold': 'bg-gray-500/20 text-gray-400',
  Lost: 'bg-gray-600/20 text-gray-500',
  Won: 'bg-emerald-500/20 text-emerald-400',
};

export function getStatusBadgeClass(status) {
  if (!status) return 'bg-gray-500/20 text-gray-400';
  if (status === 'New' || /^new$/i.test(status)) {
    return STATUS_COLORS.New;
  }
  return STATUS_COLORS[status] || 'bg-gray-500/20 text-gray-400';
}

/**
 * Extremely subtle background tint classes for Nurturing + (Hot/Warm) leads.
 * Intended to work in both dark/light themes by relying on very low opacity.
 */
export function getNurtureTemperatureTintClass(status, temperature, { includeHover = true } = {}) {
  const s = String(status || '').trim().toLowerCase();
  if (s !== 'nurturing') return '';
  const t = String(temperature || '').trim().toLowerCase();
  if (t === 'hot') {
    return includeHover
      ? 'bg-orange-500/5 hover:bg-orange-500/8'
      : 'bg-orange-500/5';
  }
  if (t === 'warm') {
    return includeHover
      ? 'bg-amber-500/5 hover:bg-amber-500/8'
      : 'bg-amber-500/5';
  }
  return '';
}

export function getOwnerDisplay(lead) {
  return lead?.assigned_to_name || lead?.assigned_to || lead?.presales_agent || '—';
}

/** Latest timeline note, or presales description from import. */
export function getRecentNote(lead) {
  const updates = dedupeContextUpdates(lead?.context_updates || []);
  const latest = updates.find((u) => (u.description || '').trim());
  if (latest?.description?.trim()) return latest.description.trim();
  const presales = (lead?.presales_description || '').trim();
  return presales || null;
}

export function getLeadInitials(lead) {
  const a = lead?.first_name?.charAt(0) || '';
  const b = lead?.last_name?.charAt(0) || '';
  return (a + b).toUpperCase() || '?';
}

/** Deterministic hue 0–360 from string */
export function avatarHue(seed) {
  const s = String(seed || 'lead');
  let hash = 0;
  for (let i = 0; i < s.length; i += 1) {
    hash = s.charCodeAt(i) + ((hash << 5) - hash);
  }
  return Math.abs(hash) % 360;
}

export function buildPendingTaskMap(tasks) {
  const map = new Map();
  if (!Array.isArray(tasks)) return map;
  for (const t of tasks) {
    if (t.status !== 'pending' || !t.lead_id) continue;
    map.set(t.lead_id, (map.get(t.lead_id) || 0) + 1);
  }
  return map;
}

export function getEarliestTaskDue(tasks, leadId) {
  if (!leadId || !Array.isArray(tasks)) return null;
  const pending = tasks.filter((t) => t.lead_id === leadId && t.status === 'pending' && t.due_date);
  if (!pending.length) return null;
  pending.sort((a, b) => String(a.due_date).localeCompare(String(b.due_date)));
  return pending[0];
}

export function formatFollowUp(lead, pendingTasks = [], taskMap = null) {
  if (lead?.next_action_date) {
    return formatDateTime(lead.next_action_date);
  }
  const count = taskMap?.get(lead?.id);
  if (count && Array.isArray(pendingTasks)) {
    const earliest = getEarliestTaskDue(pendingTasks, lead.id);
    if (earliest?.due_date) {
      return formatDueDateTime(earliest.due_date, earliest.due_time);
    }
  }
  return null;
}

export function formatDateTime(value) {
  if (!value) return null;
  const formatted = formatDateTimeIST(value);
  return formatted ?? String(value);
}
