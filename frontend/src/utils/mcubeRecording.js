/** MCUBE call recording URL helpers for timeline UI. */

export function isMcubeRecordingUrl(url) {
  if (!url || typeof url !== 'string') return false;
  const trimmed = url.trim();
  return /^https?:\/\//i.test(trimmed);
}

export function getMcubeRecordingFilenameNote(keyPoints) {
  if (!Array.isArray(keyPoints)) return null;
  const hit = keyPoints.find(
    (point) =>
      typeof point === 'string' &&
      (point.startsWith('Recording file:') || point.startsWith('Recording:'))
  );
  if (!hit) return null;
  if (hit.includes('(URL not provided)')) {
    return 'Recording filename received; playable link not available.';
  }
  return null;
}
