import React, { useEffect, useMemo, useState } from 'react';
import { usersAPI } from '../../services/api';

/**
 * Multi-select agent mention chips for notes.
 * selectedIds: string[] of user ids
 */
export default function NoteMentionPicker({
  selectedIds = [],
  onChange,
  disabled = false,
  'data-testid': testId = 'note-mention-picker',
}) {
  const [agents, setAgents] = useState([]);
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);

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

  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectedAgents = useMemo(
    () => agents.filter((a) => selectedSet.has(a.id)),
    [agents, selectedSet]
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return agents
      .filter((a) => !selectedSet.has(a.id))
      .filter((a) => {
        if (!q) return true;
        const name = (a.full_name || '').toLowerCase();
        const email = (a.email || '').toLowerCase();
        return name.includes(q) || email.includes(q);
      })
      .slice(0, 8);
  }, [agents, query, selectedSet]);

  const toggle = (id) => {
    if (disabled) return;
    if (selectedSet.has(id)) {
      onChange?.(selectedIds.filter((x) => x !== id));
    } else {
      onChange?.([...selectedIds, id]);
    }
    setQuery('');
    setOpen(false);
  };

  return (
    <div className="space-y-2" data-testid={testId}>
      <label className="text-crm-fg-muted text-xs uppercase tracking-wider block">
        Mention agents
      </label>
      {selectedAgents.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selectedAgents.map((a) => (
            <button
              key={a.id}
              type="button"
              disabled={disabled}
              onClick={() => toggle(a.id)}
              className="inline-flex items-center gap-1 rounded-full border border-[#C5A059]/40 bg-[#C5A059]/10 px-2 py-0.5 text-xs text-[#C5A059]"
              data-testid={`mention-chip-${a.id}`}
            >
              @{a.full_name}
              <span aria-hidden>×</span>
            </button>
          ))}
        </div>
      )}
      <div className="relative">
        <input
          type="text"
          value={query}
          disabled={disabled}
          placeholder="Search to @mention…"
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          className="w-full h-9 px-3 bg-crm-muted border border-crm-border rounded-lg text-crm-fg text-sm placeholder:text-crm-fg-muted focus:border-[#C5A059]/50 focus:outline-none"
          data-testid="mention-search-input"
        />
        {open && filtered.length > 0 && (
          <ul
            className="absolute z-20 mt-1 max-h-40 w-full overflow-auto rounded-lg border border-crm-border bg-crm-elevated shadow-lg"
            data-testid="mention-suggestions"
          >
            {filtered.map((a) => (
              <li key={a.id}>
                <button
                  type="button"
                  className="w-full px-3 py-2 text-left text-sm text-crm-fg hover:bg-white/5"
                  onClick={() => toggle(a.id)}
                  data-testid={`mention-option-${a.id}`}
                >
                  {a.full_name}
                  {a.role ? (
                    <span className="text-crm-fg-muted text-xs ml-1">({a.role})</span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
