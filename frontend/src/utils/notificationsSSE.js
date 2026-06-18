/**
 * SSE client over fetch() so we can send Authorization headers.
 * Beep audio lives in notificationAlerts.js (re-exported here for compatibility).
 */
export { playNotificationBeep } from './notificationAlerts';

export function connectNotificationsStream({ url, onNotification, onError }) {
  const controller = new AbortController();
  const signal = controller.signal;

  (async () => {
    try {
      const token = localStorage.getItem('token');
      const res = await fetch(url, {
        method: 'GET',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal,
      });
      if (!res.ok || !res.body) {
        throw new Error(`SSE failed: ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buf = '';
      let eventName = '';
      let dataLines = [];

      const flushEvent = () => {
        if (eventName === 'notification' && dataLines.length) {
          const raw = dataLines.join('\n');
          try {
            const parsed = JSON.parse(raw);
            onNotification?.(parsed);
          } catch {
            // ignore malformed
          }
        }
        eventName = '';
        dataLines = [];
      };

      while (!signal.aborted) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        // Process complete lines
        let idx;
        while ((idx = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, idx).replace(/\r$/, '');
          buf = buf.slice(idx + 1);

          if (!line) {
            flushEvent();
            continue;
          }
          if (line.startsWith(':')) continue;
          if (line.startsWith('event:')) {
            eventName = line.slice('event:'.length).trim();
            continue;
          }
          if (line.startsWith('data:')) {
            dataLines.push(line.slice('data:'.length).trimStart());
          }
        }
      }
    } catch (e) {
      if (!signal.aborted) onError?.(e);
    }
  })();

  return () => controller.abort();
}
