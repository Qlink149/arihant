/** Client-side mirror of backend context_updates deduplication. */

import { formatDateTimeIST, parseApiDate } from './datetime';

export function normalizeDescription(text) {
  return (text || '').trim().toLowerCase().replace(/\s+/g, ' ');
}

function entryTimestamp(update) {
  const raw = update.timestamp_dt || update.timestamp;
  if (!raw) return 0;
  const d = parseApiDate(raw);
  return d ? d.getTime() : 0;
}

function dedupeKey(update) {
  const noteId = (update.note_id || update.external_id || '').trim();
  if (noteId) return `id:${noteId}`;
  const agent = (update.agent || '').trim().toLowerCase();
  const type = (update.type || 'note').trim().toLowerCase();
  const desc = normalizeDescription(update.description);
  return `content:${type}|${agent}|${desc}`;
}

export function dedupeContextUpdates(updates) {
  if (!updates?.length) return [];
  const sorted = [...updates].sort((a, b) => entryTimestamp(b) - entryTimestamp(a));
  const seen = new Set();
  const kept = [];
  for (const entry of sorted) {
    const key = dedupeKey(entry);
    if (seen.has(key)) continue;
    seen.add(key);
    kept.push(entry);
  }
  return kept.sort((a, b) => entryTimestamp(b) - entryTimestamp(a));
}

export function formatTimelineAttribution(update) {
  const name = (update?.actor_name || update?.agent || 'Unknown').trim() || 'Unknown';
  const raw = update?.timestamp_dt || update?.timestamp;
  let timeStr = '';
  if (raw) {
    timeStr = formatDateTimeIST(raw) || String(raw);
  }
  return { name, timeStr, label: timeStr ? `Added by ${name} at ${timeStr}` : `Added by ${name}` };
}

export function contextUpdateKey(update) {
  const noteId = (update.note_id || update.external_id || '').trim();
  if (noteId) return `note-${noteId}`;
  const ts = update.timestamp || update.timestamp_dt || '';
  return `${update.type || 'note'}|${(update.agent || '').toLowerCase()}|${normalizeDescription(update.description)}|${ts}`;
}
