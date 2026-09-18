import { describe, expect, it } from 'vitest';
import { getMcubeRecordingFilenameNote, isMcubeRecordingUrl } from './mcubeRecording';

describe('isMcubeRecordingUrl', () => {
  it('accepts absolute http(s) URLs', () => {
    expect(isMcubeRecordingUrl('https://recordings.mcube.com/foo.wav')).toBe(true);
    expect(isMcubeRecordingUrl('http://example.com/a.wav')).toBe(true);
  });

  it('rejects bare filenames and empty values', () => {
    expect(isMcubeRecordingUrl('9489356932-20260917153010.wav')).toBe(false);
    expect(isMcubeRecordingUrl('')).toBe(false);
    expect(isMcubeRecordingUrl(null)).toBe(false);
  });
});

describe('getMcubeRecordingFilenameNote', () => {
  it('returns note when URL not provided', () => {
    const note = getMcubeRecordingFilenameNote([
      'Recording file: test.wav (URL not provided)',
    ]);
    expect(note).toMatch(/playable link not available/i);
  });

  it('returns null for full recording URL key point', () => {
    const note = getMcubeRecordingFilenameNote([
      'Recording: https://recordings.mcube.com/test.wav',
    ]);
    expect(note).toBeNull();
  });
});
