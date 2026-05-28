import {
  parseApiDate,
  formatDateTimeIST,
  formatDateIST,
  formatTimeIST,
  formatDueDateTime,
} from './datetime';

describe('parseApiDate', () => {
  it('treats naive ISO datetime as UTC', () => {
    const d = parseApiDate('2025-05-27T10:30:00');
    expect(d).not.toBeNull();
    expect(d.toISOString()).toBe('2025-05-27T10:30:00.000Z');
  });

  it('parses Z suffix the same as naive UTC', () => {
    const naive = parseApiDate('2025-05-27T10:30:00');
    const zulu = parseApiDate('2025-05-27T10:30:00Z');
    expect(naive.getTime()).toBe(zulu.getTime());
  });

  it('parses date-only as IST midnight', () => {
    const d = parseApiDate('2025-05-27');
    expect(d.toISOString()).toBe('2025-05-26T18:30:00.000Z');
  });
});

describe('formatDateTimeIST', () => {
  it('shows IST for naive UTC string (behind-by-5:30 fix)', () => {
    const formatted = formatDateTimeIST('2025-05-27T10:30:00');
    expect(formatted).toMatch(/27/);
    expect(formatted).toMatch(/May/i);
    expect(formatted).toMatch(/4:00\s*pm/i);
  });

  it('matches Z suffix input', () => {
    expect(formatDateTimeIST('2025-05-27T10:30:00Z')).toBe(
      formatDateTimeIST('2025-05-27T10:30:00'),
    );
  });
});

describe('formatDateIST', () => {
  it('formats date-only without shifting calendar day in IST', () => {
    const formatted = formatDateIST('2025-05-27');
    expect(formatted).toMatch(/27/);
    expect(formatted).toMatch(/May/i);
    expect(formatted).toMatch(/2025/);
  });
});

describe('formatTimeIST', () => {
  it('formats time in IST', () => {
    expect(formatTimeIST('2025-05-27T10:30:00Z')).toMatch(/4:00\s*pm/i);
  });
});

describe('formatDueDateTime', () => {
  it('formats date and time as IST wall clock', () => {
    const formatted = formatDueDateTime('2025-05-27', '14:00');
    expect(formatted).toMatch(/27/);
    expect(formatted).toMatch(/2:00\s*pm/i);
  });

  it('formats date-only', () => {
    const formatted = formatDueDateTime('2025-05-27', '');
    expect(formatted).toMatch(/27/);
    expect(formatted).not.toMatch(/am|pm/i);
  });
});
