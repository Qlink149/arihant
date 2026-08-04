import React, { useMemo } from 'react';
import { parseTimeTo24h, splitTimeForRole } from '../../utils/datetime';

const selectClass =
  'h-10 px-2 bg-crm-muted border border-crm-border rounded-lg text-crm-fg text-sm';

const HOURS_12 = Array.from({ length: 12 }, (_, i) => String(i + 1));
const HOURS_24 = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0'));
const MINUTES = Array.from({ length: 60 }, (_, i) => String(i).padStart(2, '0'));

export function RoleBasedTimeInput({ value, onChange, isAdmin, testId }) {
  const parts = useMemo(() => splitTimeForRole(value, isAdmin), [value, isAdmin]);

  const update = (next) => {
    if (isAdmin) {
      onChange(parseTimeTo24h(next.hour, next.minute, next.period));
    } else {
      onChange(parseTimeTo24h(next.hour, next.minute));
    }
  };

  if (isAdmin) {
    return (
      <div className="flex gap-1" data-testid={testId}>
        <select
          value={parts.hour}
          onChange={(e) => update({ ...parts, hour: e.target.value })}
          className={`${selectClass} flex-1`}
          aria-label="Hour"
        >
          {HOURS_12.map((h) => (
            <option key={h} value={h}>{h}</option>
          ))}
        </select>
        <select
          value={parts.minute}
          onChange={(e) => update({ ...parts, minute: e.target.value })}
          className={`${selectClass} flex-1`}
          aria-label="Minute"
        >
          {MINUTES.map((m) => (
            <option key={m} value={m}>{m}</option>
          ))}
        </select>
        <select
          value={parts.period}
          onChange={(e) => update({ ...parts, period: e.target.value })}
          className={`${selectClass} flex-1`}
          aria-label="AM or PM"
        >
          <option value="AM">AM</option>
          <option value="PM">PM</option>
        </select>
      </div>
    );
  }

  return (
    <div className="flex gap-1" data-testid={testId}>
      <select
        value={parts.hour}
        onChange={(e) => update({ ...parts, hour: e.target.value })}
        className={`${selectClass} flex-1`}
        aria-label="Hour"
      >
        {HOURS_24.map((h) => (
          <option key={h} value={h}>{h}</option>
        ))}
      </select>
      <span className="text-crm-fg self-center">:</span>
      <select
        value={parts.minute}
        onChange={(e) => update({ ...parts, minute: e.target.value })}
        className={`${selectClass} flex-1`}
        aria-label="Minute"
      >
        {MINUTES.map((m) => (
          <option key={m} value={m}>{m}</option>
        ))}
      </select>
    </div>
  );
}
