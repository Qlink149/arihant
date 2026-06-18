/** Helpers for lead list / table views */

import { dedupeContextUpdates } from './contextUpdates';
import { formatDateTimeIST, formatDueDateTime } from './datetime';
import { getStatusBadgeVariant } from '../constants/badgeVariants';

/** @deprecated Use getStatusBadgeVariant + CrmBadge instead */
export function getStatusBadgeClass(status) {
  const variant = getStatusBadgeVariant(status);
  return `crm-badge crm-badge--${variant}`;
}

export { getStatusBadgeVariant, STATUS_VARIANTS } from '../constants/badgeVariants';

/**
 * Row background tint for Nurturing + Hot/Warm leads.
 * Uses theme CSS vars (--nurture-row-*) with deeper orange/amber hues for scanability.
 */
export function getNurtureTemperatureTintClass(status, temperature, { includeHover = true } = {}) {
  const s = String(status || '').trim().toLowerCase();
  if (s !== 'nurturing') return '';
  const t = String(temperature || '').trim().toLowerCase();
  if (t === 'hot') {
    const base = 'nurture-row-tint-hot';
    return includeHover ? base : `${base} nurture-row-tint-static`;
  }
  if (t === 'warm') {
    const base = 'nurture-row-tint-warm';
    return includeHover ? base : `${base} nurture-row-tint-static`;
  }
  return '';
}

export function getOwnerDisplay(lead) {
  return lead?.assigned_to_name || lead?.assigned_to || lead?.presales_agent || '—';
}

/** Latest timeline note, or presales description from import. */
export function getRecentNote(lead) {
  const direct = (lead?.recent_note || '').trim();
  if (direct) return direct;
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

/** One pass: earliest pending task with due_date per lead_id. */
export function buildEarliestPendingTaskMap(tasks) {
  const map = new Map();
  if (!Array.isArray(tasks)) return map;
  for (const t of tasks) {
    if (t.status !== 'pending' || !t.lead_id || !t.due_date) continue;
    const existing = map.get(t.lead_id);
    if (!existing || String(t.due_date).localeCompare(String(existing.due_date)) < 0) {
      map.set(t.lead_id, t);
    }
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

export function formatFollowUp(lead, pendingTasks = [], taskMap = null, earliestTaskMap = null) {
  if (lead?.next_action_date) {
    return formatDateTime(lead.next_action_date);
  }
  const count = taskMap?.get(lead?.id);
  if (count) {
    const earliest =
      earliestTaskMap?.get(lead?.id) ??
      (Array.isArray(pendingTasks) ? getEarliestTaskDue(pendingTasks, lead.id) : null);
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
