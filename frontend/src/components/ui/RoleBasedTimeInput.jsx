import React, { useMemo } from 'react';
import { parseTimeTo24h, splitTimeForRole } from '../../utils/datetime';

const selectClass =
  'h-10 px-2 bg-crm-muted border border-crm-border rounded-lg text-crm-fg text-sm';

const HOURS_12_PERIOD = [
  ...[12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11].map((h) => ({
    hour: String(h),
    period: 'AM',
    label: `${h} AM`,
  })),
  ...[12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11].map((h) => ({
    hour: String(h),
    period: 'PM',
    label: `${h} PM`,
  })),
];
const HOURS_24 = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0'));
const MINUTES = Array.from({ length: 60 }, (_, i) => String(i).padStart(2, '0'));

function hourPeriodValue(hour, period) {
  return `${hour}|${period}`;
}

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
          value={hourPeriodValue(parts.hour, parts.period)}
          onChange={(e) => {
            const [hour, period] = e.target.value.split('|');
            update({ ...parts, hour, period });
          }}
          className={`${selectClass} flex-1`}
          aria-label="Hour"
        >
          {HOURS_12_PERIOD.map((opt) => (
            <option key={hourPeriodValue(opt.hour, opt.period)} value={hourPeriodValue(opt.hour, opt.period)}>
              {opt.label}
            </option>
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
