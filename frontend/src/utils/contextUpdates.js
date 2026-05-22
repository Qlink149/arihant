/** Client-side mirror of backend context_updates deduplication. */

export function normalizeDescription(text) {
  return (text || '').trim().toLowerCase().replace(/\s+/g, ' ');
}

function entryTimestamp(update) {
  const raw = update.timestamp_dt || update.timestamp;
  if (!raw) return 0;
  const t = new Date(raw).getTime();
  return Number.isNaN(t) ? 0 : t;
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

export function contextUpdateKey(update) {
  const noteId = (update.note_id || update.external_id || '').trim();
  if (noteId) return `note-${noteId}`;
  const ts = update.timestamp || update.timestamp_dt || '';
  return `${update.type || 'note'}|${(update.agent || '').toLowerCase()}|${normalizeDescription(update.description)}|${ts}`;
}
