import React, { useEffect, useMemo, useRef, useState } from 'react';
import { usersAPI } from '../../services/api';
import {
  findActiveMention,
  insertMentionAtCaret,
  syncMentionIdsFromText,
} from '../../utils/noteMentions';

/**
 * Note textarea with inline @agent autocomplete.
 * Inserts `@Full Name` into the note and syncs mentioned user ids.
 */
export default function NoteTextareaWithMentions({
  value = '',
  onChange,
  mentionedIds = [],
  onMentionsChange,
  disabled = false,
  placeholder = 'Write a note… Type @ to mention an agent',
  className = '',
  rows,
  'data-testid': testId = 'note-with-mentions',
}) {
  const [agents, setAgents] = useState([]);
  const [active, setActive] = useState(null);
  const [highlight, setHighlight] = useState(0);
  const textareaRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data } = await usersAPI.listAssignees();
        if (!cancelled) setAgents(Array.isArray(data) ? data : []);
      } catch {
        if (!cancelled) setAgents([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const suggestions = useMemo(() => {
    if (!active) return [];
    const q = (active.query || '').trim().toLowerCase();
    return agents
      .filter((a) => {
        if (!q) return true;
        const name = (a.full_name || '').toLowerCase();
        const email = (a.email || '').toLowerCase();
        return name.includes(q) || email.includes(q);
      })
      .slice(0, 8);
  }, [agents, active]);

  useEffect(() => {
    setHighlight(0);
  }, [active?.query, suggestions.length]);

  const emitTextAndMentions = (nextText, caret, forceAddIds = []) => {
    onChange?.(nextText);
    const synced = syncMentionIdsFromText(agents, mentionedIds, nextText, forceAddIds);
    onMentionsChange?.(synced);
    const nextActive = findActiveMention(nextText, caret);
    setActive(nextActive);
  };

  const handleChange = (e) => {
    const next = e.target.value;
    const caret = e.target.selectionStart ?? next.length;
    emitTextAndMentions(next, caret);
  };

  const handleSelect = (agent) => {
    if (disabled || !agent?.id) return;
    const el = textareaRef.current;
    const caret = el?.selectionStart ?? value.length;
    const { text: next, caret: nextCaret } = insertMentionAtCaret(
      value,
      caret,
      agent.full_name || ''
    );
    emitTextAndMentions(next, nextCaret, [agent.id]);
    setActive(null);
    requestAnimationFrame(() => {
      if (textareaRef.current) {
        textareaRef.current.focus();
        textareaRef.current.setSelectionRange(nextCaret, nextCaret);
      }
    });
  };

  const handleKeyDown = (e) => {
    if (!active || suggestions.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlight((h) => (h + 1) % suggestions.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlight((h) => (h - 1 + suggestions.length) % suggestions.length);
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault();
      handleSelect(suggestions[highlight] || suggestions[0]);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setActive(null);
    }
  };

  const handleSelectClick = (e) => {
    const caret = e.target.selectionStart ?? value.length;
    setActive(findActiveMention(value, caret));
  };

  return (
    <div className="relative" data-testid={testId}>
      <textarea
        ref={textareaRef}
        value={value}
        disabled={disabled}
        rows={rows}
        placeholder={placeholder}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onClick={handleSelectClick}
        onKeyUp={handleSelectClick}
        className={
          className ||
          'w-full h-32 px-4 py-3 bg-crm-muted border border-crm-border rounded-lg text-crm-fg placeholder:text-crm-fg-muted resize-none'
        }
        data-testid={`${testId}-input`}
      />
      {active && suggestions.length > 0 && (
        <ul
          className="absolute z-30 left-0 right-0 bottom-full mb-1 max-h-40 overflow-auto rounded-lg border border-crm-border bg-crm-elevated shadow-lg"
          data-testid="inline-mention-suggestions"
          role="listbox"
        >
          {suggestions.map((a, i) => (
            <li key={a.id} role="option" aria-selected={i === highlight}>
              <button
                type="button"
                className={`w-full px-3 py-2 text-left text-sm text-crm-fg hover:bg-white/5 ${
                  i === highlight ? 'bg-white/10' : ''
                }`}
                onMouseDown={(ev) => {
                  ev.preventDefault();
                  handleSelect(a);
                }}
                data-testid={`inline-mention-option-${a.id}`}
              >
                @{a.full_name}
                {a.role ? (
                  <span className="text-crm-fg-muted text-xs ml-1">({a.role})</span>
                ) : null}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
