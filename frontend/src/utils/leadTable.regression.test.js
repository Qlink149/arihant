import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { getNurtureTemperatureTintClass } from './leadTable';

const headerPath = join(
  dirname(fileURLToPath(import.meta.url)),
  '../components/leads/LeadProfileHeader.jsx'
);

describe('getNurtureTemperatureTintClass', () => {
  it('returns tint classes for nurturing hot leads', () => {
    const cls = getNurtureTemperatureTintClass('Nurturing', 'Hot', { includeHover: false });
    expect(cls).toContain('nurture-row-tint-hot');
  });
});

describe('LeadProfileHeader wiring', () => {
  it('imports getNurtureTemperatureTintClass (prevents blank lead page on Hot nurturing)', () => {
    const src = readFileSync(headerPath, 'utf8');
    expect(src).toContain("from '../../utils/leadTable'");
    expect(src).toContain('getNurtureTemperatureTintClass');
  });
});
