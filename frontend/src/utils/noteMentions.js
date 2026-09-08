/**
 * Inline @mention helpers for lead notes.
 * Aligns with backend note_notify._MENTION_RE: @Name with optional Capitalized trailing words.
 */

/** Match @tokens in note text (same shape backend resolves). */
export const MENTION_TOKEN_RE =
  /@([A-Za-z][A-Za-z0-9_.-]*(?:\s+[A-Z][A-Za-z0-9_.-]*){0,3})/g;

/**
 * Find active @query at caret (incomplete mention while typing).
 * @returns {{ start: number, end: number, query: string } | null}
 */
export function findActiveMention(text, caret) {
  const value = text || '';
  const pos = Math.max(0, Math.min(caret ?? value.length, value.length));
  const before = value.slice(0, pos);
  const match = before.match(/(^|[\s([{'"')])@([A-Za-z0-9_.\s-]*)$/);
  if (!match) return null;
  const query = match[2] || '';
  // Don't treat a completed multi-word mention that already ends with space as active
  if (query.includes('  ')) return null;
  const atIndex = before.lastIndexOf('@');
  if (atIndex < 0) return null;
  return { start: atIndex, end: pos, query };
}

/**
 * Replace active @query with `@Full Name ` and return new text + caret.
 */
export function insertMentionAtCaret(text, caret, fullName) {
  const value = text || '';
  const name = (fullName || '').trim();
  if (!name) {
    return { text: value, caret: caret ?? value.length };
  }
  const active = findActiveMention(value, caret);
  const insert = `@${name} `;
  if (!active) {
    const pos = caret ?? value.length;
    const next = value.slice(0, pos) + insert + value.slice(pos);
    return { text: next, caret: pos + insert.length };
  }
  const next = value.slice(0, active.start) + insert + value.slice(active.end);
  return { text: next, caret: active.start + insert.length };
}

/**
 * Collect @Name tokens from note text (lowercased for matching).
 */
export function extractMentionTokens(text) {
  const names = [];
  const re = new RegExp(MENTION_TOKEN_RE.source, 'g');
  let m;
  while ((m = re.exec(text || '')) !== null) {
    const token = (m[1] || '').trim();
    if (token) names.push(token);
  }
  return names;
}

/**
 * Keep/add user ids whose full_name matches @tokens in text (or were just selected).
 * @param {Array<{id: string, full_name?: string}>} agents
 * @param {string[]} previousIds
 * @param {string} text
 * @param {string[]} [forceAddIds] ids to always include (e.g. just selected)
 */
export function syncMentionIdsFromText(agents, previousIds, text, forceAddIds = []) {
  const tokens = extractMentionTokens(text).map((t) => t.toLowerCase());
  const byId = new Map((agents || []).map((a) => [a.id, a]));
  const next = new Set(forceAddIds.filter(Boolean));

  for (const id of previousIds || []) {
    const agent = byId.get(id);
    const fn = (agent?.full_name || '').trim().toLowerCase();
    if (fn && tokens.some((t) => fn === t || fn.startsWith(t) || t.startsWith(fn))) {
      next.add(id);
    }
  }

  for (const agent of agents || []) {
    const fn = (agent.full_name || '').trim().toLowerCase();
    if (!fn || !agent.id) continue;
    if (tokens.some((t) => fn === t || fn.startsWith(t) || t.startsWith(fn))) {
      next.add(agent.id);
    }
  }

  return [...next];
}

/**
 * Split note text into plain / mention segments for highlighting.
 * @returns {Array<{ type: 'text' | 'mention', value: string }>}
 */
export function splitMentionSegments(text) {
  const value = text || '';
  if (!value) return [];
  const segments = [];
  const re = new RegExp(MENTION_TOKEN_RE.source, 'g');
  let last = 0;
  let m;
  while ((m = re.exec(value)) !== null) {
    if (m.index > last) {
      segments.push({ type: 'text', value: value.slice(last, m.index) });
    }
    segments.push({ type: 'mention', value: m[0] });
    last = m.index + m[0].length;
  }
  if (last < value.length) {
    segments.push({ type: 'text', value: value.slice(last) });
  }
  return segments;
}

/**
 * Names stored on the entry but not present as @tokens in description (legacy picker-only).
 */
export function missingMentionNames(description, mentionedNames = []) {
  const text = (description || '').toLowerCase();
  return (mentionedNames || [])
    .map((n) => (n || '').trim())
    .filter(Boolean)
    .filter((name) => {
      const needle = `@${name}`.toLowerCase();
      const bare = name.toLowerCase();
      return !text.includes(needle) && !text.includes(`@${bare}`);
    });
}
